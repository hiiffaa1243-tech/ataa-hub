"""Moyasar flow (PRD 6.1 and section 11). Moyasar's answer is injected, so no network is needed."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from ataa_hub import payments
from ataa_hub.tests.factories import make_project


def moyasar_payment(donation, status="paid", amount=None, payment_id=None):
	return {
		"id": payment_id or "11111111-2222-3333-4444-" + frappe.generate_hash(length=12),
		"status": status,
		"amount": amount if amount is not None else int(round(flt(donation["amount"]) * 100)),
		"currency": "SAR",
		"created_at": "2026-11-17T12:00:00.000Z",
		"metadata": {"donation_id": donation["donation_id"]},
		"source": {"type": "creditcard", "company": "visa", "number": "4111-11XX-XXXX-1111"},
	}


class TestMoyasarFlow(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_project("TSTPAY-01")
		settings = frappe.get_single("Moyasar Settings")
		settings.publishable_key = "pk_test_fake"
		settings.secret_key = "sk_test_fake"
		settings.webhook_secret = "whsec_fake"
		settings.save()

	def collected(self):
		return flt(frappe.db.get_value("Donation Project", "TSTPAY-01", "collected_amount"))

	def test_pending_donation_does_not_touch_balance(self):
		before = self.collected()
		pending = payments.create_pending_donation_for("tstpay-01", 150, "Test", "+966500000123")
		self.assertEqual(pending["amount_halalas"], 15000)
		self.assertEqual(frappe.db.get_value("Donation", pending["donation_id"], "status"), "Pending")
		self.assertEqual(self.collected(), before)

	def test_callback_and_webhook_together_record_once(self):
		pending = payments.create_pending_donation_for("TSTPAY-01", 200)
		payment = moyasar_payment(pending)
		before = self.collected()

		first = payments.verify_and_record_payment(payment["id"], payment=payment)  # callback
		second = payments.verify_and_record_payment(payment["id"], payment=payment)  # webhook

		self.assertEqual((first.reason, second.reason), ("recorded", "already_paid"))
		self.assertTrue(second.ok)
		self.assertEqual(self.collected(), before + 200)

	def test_amount_changed_in_browser_is_not_accepted(self):
		pending = payments.create_pending_donation_for("TSTPAY-01", 500)
		payment = moyasar_payment(pending, amount=100)  # paid 1 SAR instead of 500

		result = payments.verify_and_record_payment(payment["id"], payment=payment)
		self.assertEqual(result.reason, "amount_mismatch")
		self.assertEqual(frappe.db.get_value("Donation", pending["donation_id"], "status"), "Pending")

	def test_failed_payment_marks_donation_failed(self):
		pending = payments.create_pending_donation_for("TSTPAY-01", 100)
		payment = moyasar_payment(pending, status="failed")
		payments.verify_and_record_payment(payment["id"], payment=payment)
		self.assertEqual(frappe.db.get_value("Donation", pending["donation_id"], "status"), "Failed")

	def test_invalid_payment_id_is_ignored(self):
		self.assertEqual(payments.verify_and_record_payment("../../etc").reason, "invalid_payment_id")

	def test_webhook_rejects_wrong_secret(self):
		frappe.local.form_dict = frappe._dict(secret_token="wrong", data={"id": "x"})
		frappe.local.response.pop("http_status_code", None)
		with patch.object(payments, "verify_and_record_payment") as verify:
			body = payments.moyasar_webhook()
		self.assertEqual(frappe.local.response.pop("http_status_code"), 401)
		self.assertFalse(body["ok"])
		verify.assert_not_called()

	def test_webhook_with_right_secret_verifies_with_moyasar(self):
		pending = payments.create_pending_donation_for("TSTPAY-01", 120)
		payment = moyasar_payment(pending)
		frappe.local.form_dict = frappe._dict(
			secret_token="whsec_fake", type="payment_paid", data={"id": payment["id"]}
		)
		with patch.object(payments, "fetch_payment", return_value=payment) as fetch:
			body = payments.moyasar_webhook()
		fetch.assert_called_once_with(payment["id"])  # the webhook body itself is never trusted
		self.assertEqual(body["result"], "recorded")

	def test_reconciliation_finds_payment_missing_in_platform(self):
		from ataa_hub.ataa_hub.report.moyasar_reconciliation import moyasar_reconciliation as report

		orphan = {
			"id": "99999999-8888-7777-6666-555555555555",
			"status": "paid",
			"amount": 30000,
			"currency": "SAR",
			"created_at": "2026-11-17T10:00:00.000Z",
			"metadata": {},
		}
		with patch.object(report, "list_paid_payments", return_value=[orphan]):
			_columns, rows, *_rest = report.execute({"from_date": "2026-11-01", "to_date": "2026-11-30"})
		self.assertIn("Missing in Platform", [r["result"] for r in rows])
