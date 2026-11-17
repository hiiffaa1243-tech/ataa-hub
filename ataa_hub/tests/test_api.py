"""API v2 rules (API.md §5–7): idempotency, auth, validation, project and event rules, gifts, GL.

Endpoints are called as Python functions while impersonating the integration user,
so these tests are fast and run inside a transaction that is rolled back afterwards.
The real HTTP stack (Authorization header, wrong key -> 401) is covered in test_api_http.py.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from ataa_hub.accounting import get_project_balance
from ataa_hub.api import v1
from ataa_hub.ataa_hub.doctype.donation.donation import Donation
from ataa_hub.tests.factories import (
	account,
	gl_lines,
	iso_ago,
	make_api_client,
	make_event,
	make_project,
	reference,
	settings,
	unique,
)

POS = {"terminal_id": "T01-TEST", "card_scheme": "mada", "rrn": "432118005731"}


class APITestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.code1, cls.code2, cls.code_off = unique("API1"), unique("API2"), unique("APIOFF")
		cls.p1 = make_project(
			cls.code1,
			impact_unit_label="معتمر سُقي",
			impact_units_per_sar=1,
			donation_options=[{"label": "Option 100", "amount": 100}],
		).name
		cls.p2 = make_project(cls.code2).name
		cls.p_off = make_project(cls.code_off, status="Completed").name
		cls.store = make_api_client(unique("Store"), "Online Store")
		cls.pos = make_api_client(unique("POS"), "POS", allowed=[cls.p1])
		cls.inactive = make_api_client(unique("Inactive"), "Online Store", active=0)

	def tearDown(self):
		frappe.set_user("Administrator")

	def call(self, endpoint, client, **payload):
		frappe.set_user(client.integration_user if client else "Guest")
		frappe.local.response.pop("http_status_code", None)
		body = endpoint(**payload)
		status = frappe.local.response.pop("http_status_code", 200)
		frappe.set_user("Administrator")
		return status, body

	def payload(self, **overrides):
		data = {
			"external_reference": reference(),
			"project_code": self.code1,
			"amount": 250.00,
			"paid_at": iso_ago(),
			"payment_reference": reference("pay"),
			"donor": {"name": "Test Donor", "mobile": "+966500000099"},
		}
		data.update(overrides)
		return data

	def collected(self, project=None):
		return flt(get_project_balance(project or self.p1).donation_income)


class TestCreateDonation(APITestCase):
	def test_create_posts_one_journal_entry_and_returns_201(self):
		before = self.collected()
		status, body = self.call(v1.create_donation, self.store, **self.payload())

		self.assertEqual(status, 201, body)
		data = body["data"]
		self.assertEqual(
			(data["status"], data["duplicate"], data["project_code"]), ("Paid", False, self.code1)
		)
		self.assertEqual((data["impact_units"], data["impact_unit_label"]), (250.0, "معتمر سُقي"))
		self.assertIsNone(data["gift"])
		self.assertIsNone(data["event_code"])
		self.assertIn("/verify/", data["receipt_verification_url"])
		self.assertEqual(self.collected(), before + 250)

		donation = frappe.get_doc("Donation", data["donation_id"])
		self.assertEqual(donation.docstatus, 1)
		self.assertEqual(donation.channel, "Online Store")  # from the client, not the body
		self.assertEqual(donation.idempotency_key, f"{self.store.name}:{data['external_reference']}")
		lines = gl_lines(donation.journal_entry)
		self.assertEqual(
			{(line.account, line.project) for line in lines},
			{(account("Online Store Clearing"), self.p1), (settings().restricted_income_account, self.p1)},
		)

	def test_same_request_twice_is_recorded_once(self):
		payload = self.payload()
		before = self.collected()
		first_status, first = self.call(v1.create_donation, self.store, **payload)
		second_status, second = self.call(v1.create_donation, self.store, **payload)

		self.assertEqual((first_status, second_status), (201, 200))
		self.assertTrue(second["data"]["duplicate"])
		self.assertEqual(first["data"]["donation_id"], second["data"]["donation_id"])
		self.assertEqual(self.collected(), before + 250)
		self.assertEqual(
			frappe.db.count("Journal Entry", {"ataa_reference_name": first["data"]["donation_id"]}), 1
		)

	def test_reused_reference_with_different_values_is_409(self):
		payload = self.payload()
		self.call(v1.create_donation, self.store, **payload)
		status, body = self.call(
			v1.create_donation, self.store, **{**payload, "amount": 999, "project_code": self.code2}
		)
		self.assertEqual(status, 409)
		self.assertEqual(body["error"]["code"], "DUPLICATE_CONFLICT")
		self.assertEqual(body["error"]["details"]["conflicting_fields"], ["project_code", "amount"])

	def test_replay_after_refund_returns_refunded_and_records_nothing(self):
		payload = self.payload()
		_, body = self.call(v1.create_donation, self.store, **payload)
		donation = frappe.get_doc("Donation", body["data"]["donation_id"])
		donation.cancel_reason = "Store refunded the order"
		donation.save()
		donation.cancel()

		status, body = self.call(v1.create_donation, self.store, **payload)
		self.assertEqual((status, body["data"]["status"], body["data"]["duplicate"]), (200, "Refunded", True))
		self.assertEqual(
			frappe.db.count("Donation", {"external_reference": payload["external_reference"]}), 1
		)

	def test_same_reference_from_two_clients_is_two_donations(self):
		ref = reference()
		s1, _ = self.call(v1.create_donation, self.store, **self.payload(external_reference=ref))
		s2, _ = self.call(v1.create_donation, self.pos, **self.payload(external_reference=ref, pos=POS))
		self.assertEqual((s1, s2), (201, 201))

	def test_failure_after_insert_rolls_back_everything(self):
		"""If posting fails, no Donation, no JE: the client can retry the same reference."""
		payload = self.payload(donor={"name": "Rollback", "mobile": "+966500000555"})
		with patch.object(Donation, "make_journal_entry", side_effect=RuntimeError("ledger down")):
			status, body = self.call(v1.create_donation, self.store, **payload)

		self.assertEqual((status, body["error"]["code"]), (500, "INTERNAL_ERROR"))
		self.assertFalse(frappe.db.exists("Donation", {"external_reference": payload["external_reference"]}))
		self.assertFalse(frappe.db.exists("Customer", {"donor_mobile": "+966500000555"}))

		status, _ = self.call(v1.create_donation, self.store, **payload)  # retry works
		self.assertEqual(status, 201)

	def test_pos_donation_is_stored_with_terminal_data(self):
		status, body = self.call(
			v1.create_donation, self.pos, **self.payload(pos={**POS, "card_scheme": "MADA"})
		)
		self.assertEqual(status, 201, body)
		d = frappe.get_doc("Donation", body["data"]["donation_id"])
		self.assertEqual(
			(d.channel, d.terminal_id, d.card_scheme, d.rrn), ("POS", "T01-TEST", "mada", POS["rrn"])
		)
		debit = next(line for line in gl_lines(d.journal_entry) if line.debit)
		self.assertEqual(debit.account, account("mada POS Clearing"))

	def test_returning_donor_is_matched_by_mobile(self):
		mobile = "+966500000777"
		self.call(v1.create_donation, self.store, **self.payload(donor={"name": "A", "mobile": mobile}))
		self.call(
			v1.create_donation, self.store, **self.payload(donor={"name": "A", "mobile": mobile}, amount=100)
		)
		self.assertEqual(frappe.db.count("Customer", {"donor_mobile": mobile}), 1)
		customer = frappe.db.get_value("Customer", {"donor_mobile": mobile}, "name")
		self.assertEqual(flt(frappe.db.get_value("Customer", customer, "lifetime_giving")), 350)

	def test_anonymous_donation_creates_no_donor(self):
		payload = self.payload()
		payload.pop("donor")
		status, body = self.call(v1.create_donation, self.store, **payload)
		self.assertEqual(status, 201)
		self.assertIsNone(frappe.db.get_value("Donation", body["data"]["donation_id"], "donor"))


class TestGift(APITestCase):
	def gift(self, **overrides):
		return {
			"recipient_name": "Test Recipient",
			"recipient_email": "recipient@example.test",
			"occasion": "Eid",
			"message": "عيدكم مبارك",
			**overrides,
		}

	def test_gift_donation_returns_private_link(self):
		status, body = self.call(v1.create_donation, self.store, **self.payload(gift=self.gift()))
		self.assertEqual(status, 201, body)
		gift = body["data"]["gift"]
		self.assertIn("/gift/", gift["url"])
		self.assertEqual(len(gift["url"].rsplit("/", 1)[1]), 32)
		self.assertIsInstance(gift["email_sent"], bool)

		d = frappe.get_doc("Donation", body["data"]["donation_id"])
		self.assertEqual(
			(d.is_gift, d.recipient_name, d.occasion, d.show_amount_on_gift), (1, "Test Recipient", "Eid", 0)
		)

	def test_gift_email_is_queued_when_email_is_configured(self):
		_, body = self.call(v1.create_donation, self.store, **self.payload(gift=self.gift()))
		if body["data"]["gift"]["email_sent"]:
			self.assertTrue(
				frappe.db.exists(
					"Email Queue",
					{"reference_doctype": "Donation", "reference_name": body["data"]["donation_id"]},
				)
			)

	def test_mobile_only_gift_sends_no_email(self):
		gift = self.gift(recipient_email=None, recipient_mobile="+966500000123")
		status, body = self.call(v1.create_donation, self.store, **self.payload(gift=gift))
		self.assertEqual(status, 201, body)
		self.assertFalse(body["data"]["gift"]["email_sent"])

	def test_gift_needs_a_way_to_reach_the_recipient(self):
		gift = {"recipient_name": "X", "occasion": "Birthday", "show_amount": "yes"}
		status, body = self.call(v1.create_donation, self.store, **self.payload(gift=gift))
		self.assertEqual(status, 400)
		self.assertEqual(
			set(body["error"]["details"]), {"gift.recipient_email", "gift.occasion", "gift.show_amount"}
		)

	def test_replay_with_other_recipient_is_409(self):
		payload = self.payload(gift=self.gift())
		self.call(v1.create_donation, self.store, **payload)
		status, body = self.call(
			v1.create_donation, self.store, **{**payload, "gift": self.gift(recipient_name="Someone else")}
		)
		self.assertEqual(status, 409)
		self.assertEqual(body["error"]["details"]["conflicting_fields"], ["gift"])


class TestEvent(APITestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.event = make_event(projects=[cls.p1], terminals=[(cls.pos.name, "T01-TEST")])
		cls.closed = make_event(projects=[cls.p1], terminals=[(cls.pos.name, "T01-TEST")], status="Closed")

	def test_pos_donation_at_event(self):
		status, body = self.call(
			v1.create_donation, self.pos, **self.payload(pos=POS, event_code=self.event.name.lower())
		)
		self.assertEqual(status, 201, body)
		self.assertEqual(body["data"]["event_code"], self.event.name)
		self.assertEqual(
			frappe.db.get_value("Donation", body["data"]["donation_id"], "fundraising_event"), self.event.name
		)

	def test_unknown_closed_or_outside_window_is_event_not_active(self):
		for code, paid_at in (
			("NO-SUCH-EVENT", iso_ago()),
			(self.closed.name, iso_ago()),
			(self.event.name, iso_ago(48)),
		):
			status, body = self.call(
				v1.create_donation, self.pos, **self.payload(pos=POS, event_code=code, paid_at=paid_at)
			)
			self.assertEqual((status, body["error"]["code"]), (403, "EVENT_NOT_ACTIVE"), code)

	def test_unregistered_terminal(self):
		status, body = self.call(
			v1.create_donation,
			self.pos,
			**self.payload(pos={**POS, "terminal_id": "T09-TEST"}, event_code=self.event.name),
		)
		self.assertEqual((status, body["error"]["code"]), (403, "TERMINAL_NOT_IN_EVENT"))
		self.assertEqual(body["error"]["details"], {"event_code": self.event.name, "terminal_id": "T09-TEST"})

	def test_project_not_in_event(self):
		status, body = self.call(
			v1.create_donation,
			self.store,
			**self.payload(project_code=self.code2, event_code=self.event.name),
		)
		self.assertEqual((status, body["error"]["code"]), (403, "PROJECT_NOT_ALLOWED"))

	def test_list_projects_for_event(self):
		_, body = self.call(v1.list_projects, self.store, event_code=self.event.name)
		self.assertEqual([p["project_code"] for p in body["data"]], [self.code1])
		status, body = self.call(v1.list_projects, self.store, event_code=self.closed.name)
		self.assertEqual((status, body["error"]["code"]), (403, "EVENT_NOT_ACTIVE"))

	def test_event_terminal_must_be_a_pos_client(self):
		with self.assertRaises(frappe.ValidationError):
			make_event(projects=[self.p1], terminals=[(self.store.name, "T01")])


class TestAuthAndRules(APITestCase):
	def test_missing_credentials_is_401(self):
		status, body = self.call(v1.create_donation, None, **self.payload())
		self.assertEqual((status, body["error"]["code"]), (401, "AUTH_REQUIRED"))

	def test_inactive_client_is_403(self):
		status, body = self.call(v1.create_donation, self.inactive, **self.payload())
		self.assertEqual((status, body["error"]["code"]), (403, "CLIENT_INACTIVE"))

	def test_staff_user_is_not_an_api_client(self):
		frappe.local.response.pop("http_status_code", None)
		body = v1.list_projects()
		self.assertEqual(frappe.local.response.pop("http_status_code"), 403)
		self.assertEqual(body["error"]["code"], "NOT_AN_API_CLIENT")

	def test_project_rules(self):
		cases = (
			(self.store, "NOPE-99", 404, "PROJECT_NOT_FOUND"),
			(self.store, self.code_off, 403, "PROJECT_INACTIVE"),
			(self.pos, self.code2, 403, "PROJECT_NOT_ALLOWED"),
		)
		for client, code, http_status, error in cases:
			extra = {"pos": POS} if client is self.pos else {}
			status, body = self.call(v1.create_donation, client, **self.payload(project_code=code, **extra))
			self.assertEqual((status, body["error"]["code"]), (http_status, error), code)

	def test_all_invalid_fields_are_reported_together(self):
		status, body = self.call(
			v1.create_donation,
			self.store,
			**self.payload(
				amount=0,
				payment_reference="",
				currency="USD",
				paid_at=iso_ago(hours=-3),  # 3 hours in the future
				donor={"mobile": "0500000000", "email": "not-an-email"},
			),
		)
		self.assertEqual((status, body["error"]["code"]), (400, "VALIDATION_ERROR"))
		self.assertEqual(
			set(body["error"]["details"]),
			{"amount", "payment_reference", "currency", "paid_at", "donor.mobile", "donor.email"},
		)

	def test_amount_rules(self):
		for amount, message in (
			(-5, "greater than 0"),
			(10.123, "2 decimal"),
			("abc", "number"),
			(True, "number"),
		):
			status, body = self.call(v1.create_donation, self.store, **self.payload(amount=amount))
			self.assertEqual(status, 400, amount)
			self.assertIn(message, body["error"]["details"]["amount"])

	def test_paid_at_requires_timezone(self):
		status, body = self.call(
			v1.create_donation, self.store, **self.payload(paid_at="2026-01-01T10:00:00")
		)
		self.assertEqual(status, 400)
		self.assertIn("Timezone", body["error"]["details"]["paid_at"])

	def test_pos_client_must_send_terminal_fields(self):
		status, body = self.call(
			v1.create_donation, self.pos, **self.payload(pos={"card_scheme": "diners", "rrn": "123"})
		)
		self.assertEqual(status, 400)
		self.assertEqual(set(body["error"]["details"]), {"pos.terminal_id", "pos.card_scheme", "pos.rrn"})

		status, body = self.call(v1.create_donation, self.pos, **self.payload())
		self.assertEqual(status, 400)
		self.assertIn("pos", body["error"]["details"])


class TestListAndGet(APITestCase):
	def test_list_projects_returns_only_open_and_allowed(self):
		_, body = self.call(v1.list_projects, self.store)
		codes = {p["project_code"] for p in body["data"]}
		self.assertTrue({self.code1, self.code2} <= codes)
		self.assertNotIn(self.code_off, codes)

		_, body = self.call(v1.list_projects, self.pos)
		self.assertEqual([p["project_code"] for p in body["data"]], [self.code1])
		project = body["data"][0]
		self.assertEqual(project["donation_options"], [{"label": "Option 100", "amount": 100.0}])
		self.assertEqual(
			(project["fund_type"], project["impact_unit_label"], project["impact_units_per_sar"]),
			("Restricted", "معتمر سُقي", 1.0),
		)

	def test_general_fund_is_listed_as_unrestricted(self):
		_, body = self.call(v1.list_projects, self.store)
		general = next(p for p in body["data"] if p["project_code"] == "GENERAL")
		self.assertEqual(general["fund_type"], "Unrestricted")

	def test_get_donation_only_sees_own_donations(self):
		payload = self.payload(gift={"recipient_name": "R", "recipient_mobile": "+966500000321"})
		self.call(v1.create_donation, self.store, **payload)

		status, body = self.call(
			v1.get_donation, self.store, external_reference=payload["external_reference"]
		)
		self.assertEqual(status, 200)
		self.assertEqual((body["data"]["amount"], body["data"]["status"]), (250.0, "Paid"))
		self.assertIn("/gift/", body["data"]["gift"]["url"])
		self.assertNotIn("duplicate", body["data"])

		status, body = self.call(v1.get_donation, self.pos, external_reference=payload["external_reference"])
		self.assertEqual((status, body["error"]["code"]), (404, "DONATION_NOT_FOUND"))

	def test_last_request_time_is_recorded(self):
		frappe.db.set_value("Donation API Client", self.store.name, "last_request_on", None)
		self.call(v1.list_projects, self.store)
		self.assertIsNotNone(frappe.db.get_value("Donation API Client", self.store.name, "last_request_on"))
