"""M2: the Moyasar flow on Draft → Submit (PRD §7.1). Payments are injected; no network."""

import uuid

import frappe
from frappe.tests import IntegrationTestCase

from ataa_hub import payments
from ataa_hub.tests.factories import make_project


def fake_payment(donation_id, halalas, status="paid", currency="SAR"):
	pid = str(uuid.uuid4())
	return pid, {
		"id": pid,
		"status": status,
		"amount": halalas,
		"currency": currency,
		"metadata": {"donation_id": donation_id},
		"source": {"type": "creditcard", "company": "visa", "number": "4111-11XX-XXXX-1111"},
	}


class TestMoyasarFlow(IntegrationTestCase):
	def setUp(self):
		ms = frappe.get_single("Moyasar Settings")
		ms.publishable_key = "pk_test_dummy"
		ms.secret_key = "sk_test_dummy"
		ms.webhook_secret = "whsec-test"
		ms.save(ignore_permissions=True)
		self.code = f"PAY-{frappe.generate_hash(length=5).upper()}"
		self.project = make_project(
			code=self.code, allow_custom_amount=0, donation_options=[{"label": "100", "amount": 100}]
		).name

	def pending(self, amount=100, **kw):
		return payments.create_pending_donation_for(self.code, amount, **kw)

	def test_pending_donation_is_a_draft(self):
		res = self.pending(mobile="+966500007777", donor_name="Web Donor")
		d = frappe.get_doc("Donation", res["donation_id"])
		self.assertEqual((d.docstatus, d.payment_status, d.channel), (0, "Awaiting Payment", "Website"))
		self.assertEqual(res["amount_halalas"], 10000)
		self.assertEqual(res["publishable_key"], "pk_test_dummy")
		self.assertNotIn("sk_test", str(res))  # the secret never leaves the server
		self.assertTrue(d.donor)

	def test_fixed_amount_project_rejects_custom_amount(self):
		with self.assertRaises(frappe.ValidationError):
			self.pending(amount=77)

	def test_paid_payment_submits_once(self):
		donation_id = self.pending()["donation_id"]
		pid, payment = fake_payment(donation_id, 10000)

		first = payments.verify_and_record_payment(pid, payment)
		second = payments.verify_and_record_payment(pid, payment)  # webhook after callback

		self.assertEqual((first.reason, second.reason), ("recorded", "already_paid"))
		d = frappe.get_doc("Donation", donation_id)
		self.assertEqual((d.docstatus, d.payment_status, d.idempotency_key), (1, "Paid", f"moyasar:{pid}"))
		self.assertEqual(
			frappe.db.count("Journal Entry", {"ataa_reference_name": donation_id, "docstatus": 1}), 1
		)

	def test_tampered_amount_is_never_recorded(self):
		donation_id = self.pending()["donation_id"]
		pid, payment = fake_payment(donation_id, 100)  # 1 SAR instead of 100
		result = payments.verify_and_record_payment(pid, payment)
		self.assertEqual(result.reason, "amount_mismatch")
		self.assertEqual(frappe.db.get_value("Donation", donation_id, "docstatus"), 0)

	def test_failed_payment_stays_draft(self):
		donation_id = self.pending()["donation_id"]
		pid, payment = fake_payment(donation_id, 10000, status="failed")
		self.assertEqual(payments.verify_and_record_payment(pid, payment).reason, "failed")
		self.assertEqual(
			frappe.db.get_value("Donation", donation_id, ["docstatus", "payment_status"]), (0, "Failed")
		)

	def test_bad_or_unknown_ids(self):
		self.assertEqual(payments.verify_and_record_payment("not-a-uuid").reason, "invalid_payment_id")
		pid, payment = fake_payment("DON-NOPE-0001", 10000)
		self.assertEqual(payments.verify_and_record_payment(pid, payment).reason, "unknown_donation")

	def test_webhook_rejects_wrong_secret(self):
		frappe.local.form_dict = frappe._dict(secret_token="wrong", data={"id": str(uuid.uuid4())})
		frappe.local.response.pop("http_status_code", None)
		body = payments.moyasar_webhook()
		self.assertEqual(frappe.local.response.pop("http_status_code"), 401)
		self.assertFalse(body["ok"])
