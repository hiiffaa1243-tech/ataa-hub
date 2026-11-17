"""M5: memberships (PRD §7.5) with a fake Moyasar.

The fake keeps payments and tokens in memory. Each charge takes the next outcome
from `outcomes` ("paid", "failed", "timeout", "error"), so a test can script a
whole dunning story. Amounts are checked against the General Ledger.
"""

import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate

from ataa_hub import memberships, moyasar
from ataa_hub.constants import ROLE_PROFILES
from ataa_hub.tests.factories import gl_lines, make_bank_donation, make_project, make_user, settings

ACC = "acc-members@ataa.test"
ED = "ed-members@ataa.test"


class FakeMoyasar:
	def __init__(self, outcomes=("paid",)):
		self.outcomes = list(outcomes)
		self.payments, self.tokens = {}, {}
		self.charges, self.deleted = [], []

	# --- helpers for tests
	def add_token(self, status="active", last_four="1111"):
		token_id = f"token_{uuid.uuid4().hex[:20]}"
		self.tokens[token_id] = {
			"id": token_id,
			"status": status,
			"brand": "visa",
			"last_four": last_four,
			"month": "12",
			"year": "2030",
		}
		return token_id

	def signup_payment(self, intent, amount_halalas, token_id=None, status="paid"):
		payment_id = str(uuid.uuid4())
		self.payments[payment_id] = {
			"id": payment_id,
			"status": status,
			"amount": amount_halalas,
			"currency": "SAR",
			"metadata": {"membership_signup": intent},
			"source": {"type": "creditcard", "token": token_id or self.add_token()},
		}
		return payment_id

	# --- the client interface used by the app
	def fetch_payment(self, payment_id):
		if payment_id not in self.payments:
			raise moyasar.NotFound("not found", 404)
		return self.payments[payment_id]

	def charge_token(self, *, given_id, token, amount_halalas, description, metadata):
		outcome = self.outcomes.pop(0) if self.outcomes else "paid"
		self.charges.append({"id": given_id, "token": token, "amount": amount_halalas, "metadata": metadata})
		if outcome == "timeout":
			raise moyasar.MoyasarUnavailable("timeout")
		if outcome == "error":
			raise moyasar.MoyasarError("Invalid token", 400)
		self.payments[given_id] = {
			"id": given_id,
			"status": outcome,
			"amount": amount_halalas,
			"currency": "SAR",
			"metadata": metadata,
			"source": {
				"type": "token",
				"message": "INSUFFICIENT_FUNDS" if outcome == "failed" else "APPROVED",
			},
		}
		return self.payments[given_id]

	def fetch_token(self, token_id):
		if token_id not in self.tokens:
			raise moyasar.NotFound("not found", 404)
		return self.tokens[token_id]

	def delete_token(self, token_id):
		self.deleted.append(token_id)


class MembershipTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(ACC, ROLE_PROFILES["Ataa Accountant"])
		make_user(ED, ROLE_PROFILES["Ataa Executive Director"])
		ms = frappe.get_single("Moyasar Settings")
		ms.publishable_key = "pk_test_fake_publishable"
		ms.secret_key = "sk_test_fake_secret"
		ms.flags.ignore_permissions = True
		ms.save()

	def setUp(self):
		self.fake = FakeMoyasar()
		patcher = patch("ataa_hub.moyasar.get_client", return_value=self.fake)
		patcher.start()
		self.addCleanup(patcher.stop)

	def tearDown(self):
		frappe.set_user("Administrator")

	# ---------------------------------------------------------------- builders
	def donor_details(self):
		n = frappe.generate_hash(length=8)
		mobile = "+9665" + "".join(str(int(c, 16) % 10) for c in n)
		return {"full_name": f"عضو تجريبي {n[:4]}", "email": f"member-{n}@ataa.test", "mobile": mobile}

	def sign_up(self, tier="Bronze", **details):
		details = details or self.donor_details()
		form = memberships.start_signup_for(tier, **details)
		payment_id = self.fake.signup_payment(form["intent"], form["amount_halalas"])
		result = memberships.complete_signup(payment_id)
		self.assertTrue(result.ok, result.reason)
		result.payment_id = payment_id
		return result

	def member_with_due_invoice(self, tier="Bronze"):
		"""Signed-up member + their next month's invoice, already due."""
		result = self.sign_up(tier)
		sub = frappe.get_doc("Subscription", result.subscription)
		sub.process(posting_date=sub.current_invoice_start)
		invoice = frappe.get_all(
			"Sales Invoice",
			filters={"subscription": sub.name, "docstatus": 1, "outstanding_amount": (">", 0)},
			pluck="name",
		)
		self.assertEqual(len(invoice), 1)
		result.invoice = invoice[0]
		result.due = frappe.db.get_value("Sales Invoice", invoice[0], "due_date")
		return result

	def status(self, customer):
		return frappe.db.get_value("Customer", customer, "membership_status")

	def attempts(self, invoice):
		return frappe.get_all(
			"Membership Charge Attempt",
			filters={"sales_invoice": invoice},
			fields=["name", "status", "attempt_no", "next_retry_on", "payment_entry"],
			order_by="attempt_no asc, creation asc",
		)


class TestSignup(MembershipTestCase):
	def test_signup_builds_the_whole_membership(self):
		details = self.donor_details()
		r = self.sign_up("Silver", **details)

		c = frappe.get_doc("Customer", r.customer)
		self.assertEqual(
			(c.membership_tier, c.membership_status, c.membership_subscription),
			("Silver", "Active", r.subscription),
		)
		self.assertEqual(str(c.member_since), nowdate())

		# Card: token stored encrypted, masked title, never the card number
		card = frappe.get_doc("Donor Payment Method", {"customer": r.customer})
		self.assertEqual(card.title, "Visa •••• 1111 (12/30)")
		self.assertTrue(card.is_default)
		self.assertTrue(card.token().startswith("token_"))
		self.assertNotIn(
			"token_", str(frappe.db.get_value("Donor Payment Method", card.name, "moyasar_token"))
		)

		# First invoice (created by ERPNext on insert) is a membership invoice on GENERAL, paid
		inv = frappe.get_doc("Sales Invoice", r.invoice)
		self.assertEqual(
			(inv.is_membership, inv.project, flt(inv.outstanding_amount)), (1, settings().general_project, 0)
		)
		self.assertEqual(flt(inv.grand_total), 100)
		pe = frappe.get_doc("Payment Entry", r.payment_entry)
		self.assertEqual((pe.is_membership, pe.reference_no, flt(pe.paid_amount)), (1, r.payment_id, 100))

		# GL: membership income on GENERAL; clearing debited
		income = frappe.db.get_single_value("Membership Settings", "membership_income_account")
		self.assertIn(
			(income, 0.0, 100.0, settings().general_project),
			{(line.account, flt(line.debit), flt(line.credit), line.project) for line in gl_lines(r.invoice)},
		)

		# Portal user linked through the contact
		self.assertEqual(memberships.customer_for_user(details["email"]), r.customer)
		self.assertEqual(flt(c.lifetime_giving), 100)

		attempt = self.attempts(r.invoice)[0]
		self.assertEqual((attempt.status, attempt.payment_entry), ("Succeeded", r.payment_entry))

	def test_callback_twice_records_once(self):
		r = self.sign_up()
		again = memberships.complete_signup(r.payment_id)
		self.assertEqual(
			(again.ok, again.reason, again.payment_entry), (True, "already_recorded", r.payment_entry)
		)
		self.assertEqual(frappe.db.count("Subscription", {"party": r.customer}), 1)

	def test_wrong_amount_creates_nothing(self):
		form = memberships.start_signup_for("Gold", **self.donor_details())
		payment_id = self.fake.signup_payment(form["intent"], 100)  # 1 SAR instead of 250
		result = memberships.complete_signup(payment_id)
		self.assertEqual((result.ok, result.reason), (False, "amount_mismatch"))
		self.assertFalse(frappe.db.exists("Payment Entry", {"reference_no": payment_id}))

	def test_failed_payment_creates_nothing(self):
		form = memberships.start_signup_for("Bronze", **self.donor_details())
		payment_id = self.fake.signup_payment(form["intent"], form["amount_halalas"], status="failed")
		self.assertEqual(memberships.complete_signup(payment_id).reason, "failed")

	def test_token_that_cannot_be_charged_is_not_saved(self):
		form = memberships.start_signup_for("Bronze", **self.donor_details())
		token = self.fake.add_token(status="inactive")
		payment_id = self.fake.signup_payment(form["intent"], form["amount_halalas"], token_id=token)
		r = memberships.complete_signup(payment_id)
		self.assertTrue(r.ok)  # the first month is paid, so the membership exists...
		self.assertFalse(
			frappe.db.exists("Donor Payment Method", {"customer": r.customer})
		)  # ...without a card

	def test_cannot_sign_up_twice(self):
		details = self.donor_details()
		self.sign_up(**details)
		with self.assertRaises(frappe.ValidationError):
			memberships.start_signup_for("Gold", **details)

	def test_known_mobile_needs_its_own_email(self):
		details = self.donor_details()
		self.sign_up(**details)
		with self.assertRaises(frappe.ValidationError):
			memberships.start_signup_for("Gold", **{**details, "email": "someone-else@ataa.test"})


class TestCharging(MembershipTestCase):
	def test_due_invoice_is_charged_once(self):
		m = self.member_with_due_invoice("Bronze")
		charged = memberships.charge_due_invoices(today=m.due)
		self.assertEqual(
			len(
				[
					a
					for a in charged
					if frappe.db.get_value("Membership Charge Attempt", a, "sales_invoice") == m.invoice
				]
			),
			1,
		)

		[attempt] = self.attempts(m.invoice)
		self.assertEqual((attempt.status, attempt.attempt_no), ("Succeeded", 1))
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", m.invoice, "outstanding_amount")), 0)
		charge = next(c for c in self.fake.charges if c["metadata"]["invoice"] == m.invoice)
		self.assertEqual(charge["amount"], 5000)
		card = frappe.get_doc("Donor Payment Method", {"customer": m.customer})
		self.assertEqual(charge["token"], card.token())

		# Running the job again (or twice the same day) never charges again
		memberships.charge_due_invoices(today=m.due)
		self.assertEqual(len(self.attempts(m.invoice)), 1)
		self.assertEqual(flt(frappe.db.get_value("Customer", m.customer, "lifetime_giving")), 100)

	def test_not_due_yet_is_not_charged(self):
		m = self.member_with_due_invoice()
		memberships.charge_due_invoices(today=add_days(m.due, -1))
		self.assertEqual(self.attempts(m.invoice), [])

	def test_dunning_three_failures_then_suspended(self):
		m = self.member_with_due_invoice()
		self.fake.outcomes = ["failed", "failed", "failed"]
		day1 = m.due

		memberships.charge_invoice(m.invoice, today=day1)
		a = self.attempts(m.invoice)
		self.assertEqual((a[0].status, str(a[0].next_retry_on)), ("Failed", str(add_days(day1, 3))))
		self.assertEqual(self.status(m.customer), "Payment Pending")

		# Too early for the retry
		self.assertIsNone(memberships.charge_invoice(m.invoice, today=add_days(day1, 2)))

		day4 = add_days(day1, 3)
		memberships.charge_invoice(m.invoice, today=day4)
		a = self.attempts(m.invoice)
		self.assertEqual((a[1].attempt_no, str(a[1].next_retry_on)), (2, str(add_days(day4, 7))))
		self.assertEqual(self.status(m.customer), "Payment Pending")

		day11 = add_days(day4, 7)
		memberships.charge_invoice(m.invoice, today=day11)
		a = self.attempts(m.invoice)
		self.assertEqual((a[2].attempt_no, a[2].status, a[2].next_retry_on), (3, "Failed", None))
		self.assertEqual(self.status(m.customer), "Suspended")

		# Accountant notified; no 4th automatic attempt
		self.assertTrue(frappe.db.exists("Notification Log", {"for_user": ACC, "document_name": a[2].name}))
		self.assertIsNone(memberships.charge_invoice(m.invoice, today=add_days(day11, 30)))
		self.assertEqual(len(self.fake.charges), 3)

	def test_timeout_stays_processing_and_is_never_recharged(self):
		m = self.member_with_due_invoice()
		self.fake.outcomes = ["timeout"]
		memberships.charge_invoice(m.invoice, today=m.due)
		[attempt] = self.attempts(m.invoice)
		self.assertEqual(attempt.status, "Processing")

		self.assertIsNone(memberships.charge_invoice(m.invoice, today=m.due, force=True))
		self.assertEqual(len(self.fake.charges), 1)

		# Reconciliation: Moyasar never received it (404) → Failed, so dunning can continue
		memberships.resolve_stale_attempts(now=frappe.utils.add_to_date(None, hours=1))
		self.assertEqual(self.attempts(m.invoice)[0].status, "Failed")

	def test_reconciliation_finds_a_charge_that_did_go_through(self):
		m = self.member_with_due_invoice()
		self.fake.outcomes = ["timeout"]
		memberships.charge_invoice(m.invoice, today=m.due)
		[attempt] = self.attempts(m.invoice)
		given_id = frappe.db.get_value("Membership Charge Attempt", attempt.name, "moyasar_payment_id")
		# The money was actually taken at Moyasar
		self.fake.payments[given_id] = {"id": given_id, "status": "paid", "amount": 5000, "currency": "SAR"}

		memberships.resolve_stale_attempts(now=frappe.utils.add_to_date(None, hours=1))
		[attempt] = self.attempts(m.invoice)
		self.assertEqual(attempt.status, "Succeeded")
		self.assertTrue(attempt.payment_entry)

	def test_unknown_result_goes_to_needs_review(self):
		m = self.member_with_due_invoice()
		self.fake.outcomes = ["timeout"]
		memberships.charge_invoice(m.invoice, today=m.due)
		with patch.object(self.fake, "fetch_payment", side_effect=moyasar.MoyasarUnavailable("down")):
			memberships.resolve_stale_attempts(now=frappe.utils.add_to_date(None, hours=1))
		[attempt] = self.attempts(m.invoice)
		self.assertEqual(attempt.status, "Needs Review")
		self.assertIsNone(memberships.charge_invoice(m.invoice, today=add_days(m.due, 10), force=True))

	def test_moyasar_refusal_is_a_failure(self):
		m = self.member_with_due_invoice()
		self.fake.outcomes = ["error"]
		memberships.charge_invoice(m.invoice, today=m.due)
		self.assertEqual(self.attempts(m.invoice)[0].status, "Failed")

	def test_status_only_closed_by_the_system(self):
		m = self.member_with_due_invoice()
		self.fake.outcomes = ["failed"]
		memberships.charge_invoice(m.invoice, today=m.due)
		doc = frappe.get_doc("Membership Charge Attempt", self.attempts(m.invoice)[0].name)
		doc.status = "Succeeded"
		with self.assertRaises(frappe.ValidationError):
			doc.save()


class TestSelfService(MembershipTestCase):
	def test_update_card_retries_and_deletes_old_token(self):
		m = self.member_with_due_invoice()
		old_card = frappe.get_doc("Donor Payment Method", {"customer": m.customer})
		old_token = old_card.token()
		self.fake.outcomes = ["failed", "paid"]
		memberships.charge_invoice(m.invoice, today=m.due)
		self.assertEqual(self.status(m.customer), "Payment Pending")

		result = memberships.update_card(m.customer, self.fake.add_token(last_four="4242"))
		self.assertEqual(result["status"], "Active")
		self.assertIn(old_token, self.fake.deleted)
		self.assertEqual(frappe.db.get_value("Donor Payment Method", old_card.name, "status"), "Deleted")
		new_card = frappe.get_doc("Donor Payment Method", result["card"])
		self.assertEqual((new_card.is_default, new_card.last4), (1, "4242"))
		self.assertEqual(self.fake.charges[-1]["token"], new_card.token())
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", m.invoice, "outstanding_amount")), 0)

	def test_change_tier_applies_to_next_invoice(self):
		r = self.sign_up("Bronze")
		memberships.change_tier(r.customer, "Gold")
		sub = frappe.get_doc("Subscription", r.subscription)
		self.assertEqual(sub.plans[0].plan, "Gold Monthly")
		self.assertEqual(frappe.db.get_value("Customer", r.customer, "membership_tier"), "Gold")
		self.assertEqual(
			flt(frappe.db.get_value("Sales Invoice", r.invoice, "grand_total")), 50
		)  # current month unchanged

		sub.process(posting_date=sub.current_invoice_start)
		next_invoice = frappe.get_all(
			"Sales Invoice",
			filters={"subscription": sub.name, "outstanding_amount": (">", 0)},
			pluck="grand_total",
		)
		self.assertEqual([flt(x) for x in next_invoice], [250])
		with self.assertRaises(frappe.ValidationError):
			memberships.change_tier(r.customer, "Gold")

	def test_cancel_keeps_member_until_paid_month_ends(self):
		r = self.sign_up()
		paid_through = memberships.cancel_membership(r.customer)
		sub = frappe.get_doc("Subscription", r.subscription)
		self.assertEqual(sub.status, "Cancelled")
		self.assertEqual(self.status(r.customer), "Active")  # the paid month is not over yet

		# No invoice for the next month, even when ERPNext's job runs on that day
		sub.process(posting_date=paid_through)
		self.assertEqual(frappe.db.count("Sales Invoice", {"subscription": sub.name}), 1)

		memberships.close_ended_memberships(today=add_days(paid_through, -1))
		self.assertEqual(self.status(r.customer), "Active")
		memberships.close_ended_memberships(today=paid_through)
		self.assertEqual(self.status(r.customer), "Cancelled")
		with self.assertRaises(frappe.ValidationError):
			memberships.cancel_membership(r.customer)

	def test_portal_methods_use_the_logged_in_donor(self):
		from ataa_hub.portal import membership as portal

		details = self.donor_details()
		r = self.sign_up(**details)
		frappe.set_user(details["email"])
		portal.change_tier("Platinum")
		self.assertEqual(frappe.db.get_value("Customer", r.customer, "membership_tier"), "Platinum")
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			portal.cancel_membership()


class TestHonorary(MembershipTestCase):
	def test_monthly_job_grants_honorary(self):
		ms = frappe.get_single("Membership Settings")
		threshold = flt(ms.honorary_threshold) or 10000
		r = self.sign_up("Bronze")
		make_bank_donation(make_project().name, threshold, donor=r.customer)
		self.assertGreaterEqual(
			flt(frappe.db.get_value("Customer", r.customer, "lifetime_giving")), threshold
		)

		self.assertIn(r.customer, memberships.evaluate_honorary())
		c = frappe.get_doc("Customer", r.customer)
		self.assertEqual((c.membership_tier, str(c.honorary_since)), ("Honorary", nowdate()))
		# default policy: the paid membership is kept
		self.assertFalse(frappe.db.get_value("Subscription", r.subscription, "cancel_at_period_end"))
		self.assertNotIn(r.customer, memberships.evaluate_honorary())

	def test_only_executive_grants_by_hand(self):
		r = self.sign_up()
		frappe.set_user(ACC)
		with self.assertRaises(frappe.PermissionError):
			memberships.grant_honorary(r.customer)
		frappe.set_user(ED)
		self.assertEqual(memberships.grant_honorary(r.customer).membership_tier, "Honorary")
