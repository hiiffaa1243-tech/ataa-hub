"""API rules from PRD section 11: idempotency, auth, validation, project rules.

Endpoints are called as Python functions while impersonating the integration user,
so these tests are fast and run inside a transaction that is rolled back afterwards.
The real HTTP stack (Authorization header, wrong key -> 401) is covered in test_api_http.py.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from ataa_hub.api import v1
from ataa_hub.tests.factories import iso_ago, make_api_client, make_project, reference


class TestDonationAPI(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_project("TSTAPI-01")
		make_project("TSTAPI-02")
		make_project("TSTAPI-OFF", status="Closed")
		cls.store = make_api_client("Test Store", "Online Store")
		cls.pos = make_api_client("Test POS", "POS", allowed=["TSTAPI-01"])
		cls.inactive = make_api_client("Test Inactive", "Online Store", active=0)

	def tearDown(self):
		frappe.set_user("Administrator")

	# ---------------------------------------------------------------- helpers

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
			"project_code": "TSTAPI-01",
			"amount": 250.00,
			"paid_at": iso_ago(),
			"payment_reference": reference("pay"),
			"donor": {"name": "Test Donor", "mobile": "+966500000099"},
		}
		data.update(overrides)
		return data

	def collected(self, project="TSTAPI-01"):
		return flt(frappe.db.get_value("Donation Project", project, "collected_amount"))

	# --------------------------------------------------------- happy path

	def test_create_returns_201_and_updates_balance(self):
		before = self.collected()
		status, body = self.call(v1.create_donation, self.store, **self.payload())

		self.assertEqual(status, 201)
		self.assertTrue(body["ok"])
		self.assertFalse(body["data"]["duplicate"])
		self.assertEqual(body["data"]["status"], "Paid")
		self.assertEqual(self.collected(), before + 250)

		donation = frappe.get_doc("Donation", body["data"]["donation_id"])
		self.assertEqual(donation.channel, "Online Store")  # channel comes from the client, not the body
		self.assertEqual(donation.api_client, self.store.name)

	# ---------------------------------------------------------- idempotency

	def test_same_request_twice_is_recorded_once(self):
		payload = self.payload()
		before = self.collected()

		first_status, first = self.call(v1.create_donation, self.store, **payload)
		second_status, second = self.call(v1.create_donation, self.store, **payload)

		self.assertEqual(first_status, 201)
		self.assertEqual(second_status, 200)
		self.assertTrue(second["data"]["duplicate"])
		self.assertEqual(first["data"]["donation_id"], second["data"]["donation_id"])
		self.assertEqual(
			frappe.db.count(
				"Donation",
				{"api_client": self.store.name, "external_reference": payload["external_reference"]},
			),
			1,
		)
		self.assertEqual(self.collected(), before + 250)

	def test_reused_reference_with_different_amount_is_409(self):
		payload = self.payload()
		self.call(v1.create_donation, self.store, **payload)
		status, body = self.call(v1.create_donation, self.store, **{**payload, "amount": 999})

		self.assertEqual(status, 409)
		self.assertEqual(body["error"]["code"], "DUPLICATE_CONFLICT")
		self.assertEqual(body["error"]["details"]["conflicting_fields"], ["amount"])

	def test_same_reference_from_two_clients_is_two_donations(self):
		ref = reference()
		store_status, _ = self.call(v1.create_donation, self.store, **self.payload(external_reference=ref))
		pos_status, _ = self.call(
			v1.create_donation,
			self.pos,
			**self.payload(
				external_reference=ref,
				pos={"terminal_id": "T-TEST", "card_scheme": "mada", "rrn": "123456789012"},
			),
		)
		self.assertEqual((store_status, pos_status), (201, 201))

	def test_database_rejects_duplicates_even_without_the_api(self):
		ref = reference()
		values = {"api_client": self.store.name, "external_reference": ref, "channel": "Online Store"}
		from ataa_hub.tests.factories import paid_donation

		paid_donation("TSTAPI-01", 10, **values)
		with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
			paid_donation("TSTAPI-01", 10, **values)

	# ---------------------------------------------------------------- auth

	def test_missing_credentials_is_401(self):
		status, body = self.call(v1.create_donation, None, **self.payload())
		self.assertEqual(status, 401)
		self.assertEqual(body["error"]["code"], "AUTH_REQUIRED")

	def test_inactive_client_is_403(self):
		status, body = self.call(v1.create_donation, self.inactive, **self.payload())
		self.assertEqual(status, 403)
		self.assertEqual(body["error"]["code"], "CLIENT_INACTIVE")

	def test_staff_user_is_not_an_api_client(self):
		frappe.set_user("Administrator")
		frappe.local.response.pop("http_status_code", None)
		body = v1.list_projects()
		self.assertEqual(frappe.local.response.pop("http_status_code"), 403)
		self.assertEqual(body["error"]["code"], "NOT_AN_API_CLIENT")

	# --------------------------------------------------------- project rules

	def test_unknown_project_is_404(self):
		status, body = self.call(v1.create_donation, self.store, **self.payload(project_code="NOPE-99"))
		self.assertEqual(status, 404)
		self.assertEqual(body["error"]["code"], "PROJECT_NOT_FOUND")

	def test_inactive_project_is_403(self):
		status, body = self.call(v1.create_donation, self.store, **self.payload(project_code="TSTAPI-OFF"))
		self.assertEqual(status, 403)
		self.assertEqual(body["error"]["code"], "PROJECT_INACTIVE")

	def test_project_outside_client_allow_list_is_403(self):
		status, body = self.call(
			v1.create_donation,
			self.pos,
			**self.payload(
				project_code="TSTAPI-02",
				pos={"terminal_id": "T-TEST", "card_scheme": "mada", "rrn": "123456789012"},
			),
		)
		self.assertEqual(status, 403)
		self.assertEqual(body["error"]["code"], "PROJECT_NOT_ALLOWED")

	# ------------------------------------------------------------ validation

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
		self.assertEqual(status, 400)
		self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
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

	def test_pos_donation_is_stored_with_terminal_data(self):
		status, body = self.call(
			v1.create_donation,
			self.pos,
			**self.payload(
				pos={"terminal_id": "T01-HAJJ-EXPO", "card_scheme": "MADA", "rrn": "432118005731"}
			),
		)
		self.assertEqual(status, 201)
		donation = frappe.get_doc("Donation", body["data"]["donation_id"])
		self.assertEqual(
			(donation.channel, donation.terminal_id, donation.card_scheme, donation.rrn),
			("POS", "T01-HAJJ-EXPO", "mada", "432118005731"),
		)

	# ----------------------------------------------------------- donors

	def test_returning_donor_is_matched_by_mobile(self):
		mobile = "+966500000777"
		self.call(v1.create_donation, self.store, **self.payload(donor={"name": "A", "mobile": mobile}))
		self.call(
			v1.create_donation, self.store, **self.payload(donor={"name": "A", "mobile": mobile}, amount=100)
		)

		self.assertEqual(frappe.db.count("Donor", {"mobile": mobile}), 1)
		donor = frappe.get_doc("Donor", {"mobile": mobile})
		self.assertEqual((donor.donations_count, flt(donor.total_donated)), (2, 350))

	def test_anonymous_donation_creates_no_donor(self):
		payload = self.payload()
		payload.pop("donor")
		status, body = self.call(v1.create_donation, self.store, **payload)
		self.assertEqual(status, 201)
		self.assertIsNone(frappe.db.get_value("Donation", body["data"]["donation_id"], "donor"))

	# ------------------------------------------------- list / get endpoints

	def test_list_projects_returns_only_active_and_allowed(self):
		_, body = self.call(v1.list_projects, self.store)
		codes = {p["project_code"] for p in body["data"]}
		self.assertTrue({"TSTAPI-01", "TSTAPI-02"} <= codes)
		self.assertNotIn("TSTAPI-OFF", codes)

		_, body = self.call(v1.list_projects, self.pos)
		self.assertEqual([p["project_code"] for p in body["data"]], ["TSTAPI-01"])
		self.assertEqual(body["data"][0]["donation_options"], [{"label": "Option 100", "amount": 100.0}])

	def test_get_donation_only_sees_own_donations(self):
		payload = self.payload()
		self.call(v1.create_donation, self.store, **payload)

		status, body = self.call(
			v1.get_donation, self.store, external_reference=payload["external_reference"]
		)
		self.assertEqual(status, 200)
		self.assertEqual(body["data"]["amount"], 250.0)

		status, body = self.call(v1.get_donation, self.pos, external_reference=payload["external_reference"])
		self.assertEqual(status, 404)
		self.assertEqual(body["error"]["code"], "DONATION_NOT_FOUND")

	def test_last_request_time_is_recorded(self):
		frappe.db.set_value("Donation API Client", self.store.name, "last_request_on", None)
		self.call(v1.list_projects, self.store)
		self.assertIsNotNone(frappe.db.get_value("Donation API Client", self.store.name, "last_request_on"))
