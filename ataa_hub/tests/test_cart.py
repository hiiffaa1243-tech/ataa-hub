"""Cart checkout: one Moyasar payment for several donations, and bank transfer with a receipt."""

import base64
import uuid

import frappe
from frappe.tests import IntegrationTestCase

from ataa_hub import payments, reconciliation
from ataa_hub.projects import catalog
from ataa_hub.tests.factories import make_project

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


def cart_payment(ids, halalas, status="paid"):
	pid = str(uuid.uuid4())
	return pid, {
		"id": pid,
		"status": status,
		"amount": halalas,
		"currency": "SAR",
		"created_at": frappe.utils.nowdate() + "T10:00:00Z",
		"metadata": {"donation_ids": ",".join(ids)},
		"source": {"type": "creditcard", "company": "mada", "number": "4201-32XX-XXXX-1010"},
	}


class TestCart(IntegrationTestCase):
	def setUp(self):
		ms = frappe.get_single("Moyasar Settings")
		ms.publishable_key = "pk_test_dummy"
		ms.secret_key = "sk_test_dummy"
		ms.save(ignore_permissions=True)
		self.a = f"CA-{frappe.generate_hash(length=5).upper()}"
		self.b = f"CB-{frappe.generate_hash(length=5).upper()}"
		make_project(code=self.a, allow_custom_amount=0, donation_options=[{"label": "سقيا", "amount": 100}])
		make_project(code=self.b, allow_custom_amount=1)

	def items(self, gift=None):
		return [
			{"project_code": self.a, "amount": 100, "qty": 3},
			{"project_code": self.b, "amount": 55.5, "qty": 1, "gift": gift},
		]

	def test_cart_creates_one_draft_per_line_and_one_payment(self):
		res = payments.create_pending_cart_for(self.items(), donor_name="سلة", mobile="+966500007001")
		self.assertEqual(len(res["donation_ids"]), 2)
		self.assertEqual((res["amount"], res["amount_halalas"]), (355.5, 35550))
		self.assertEqual(res["metadata"], {"donation_ids": ",".join(res["donation_ids"])})
		amounts = [frappe.db.get_value("Donation", n, "amount") for n in res["donation_ids"]]
		self.assertEqual(amounts, [300, 55.5])

	def test_cart_rejects_tampered_or_bad_lines(self):
		for items in (
			[{"project_code": self.a, "amount": 1, "qty": 1}],  # not a preset of a fixed project
			[{"project_code": self.a, "amount": 100, "qty": 0}],
			[{"project_code": "NOPE-1", "amount": 100, "qty": 1}],
			[],
			[{"project_code": self.b, "amount": 10, "qty": 1}] * 21,
		):
			with self.assertRaises(frappe.ValidationError):
				payments.cart_lines(items)

	def test_one_payment_submits_every_donation_once(self):
		gift = {
			"recipient_name": "أم محمد",
			"recipient_mobile": "+966500007002",
			"occasion": "Eid",
			"show_amount": 1,
		}
		ids = payments.create_pending_cart_for(self.items(gift))["donation_ids"]
		pid, payment = cart_payment(ids, 35550)

		first = payments.verify_and_record_payment(pid, payment)
		again = payments.verify_and_record_payment(pid, payment)  # webhook after the callback
		self.assertEqual((first.reason, again.reason), ("recorded", "already_paid"))
		self.assertEqual(len(first.donations), 2)
		rows = [frappe.db.get_value("Donation", n, ["docstatus", "idempotency_key", "is_gift"]) for n in ids]
		self.assertEqual(rows, [(1, f"moyasar:{pid}:1", 0), (1, f"moyasar:{pid}:2", 1)])

		# reconciliation compares Moyasar's one payment with the sum of both donations
		rows = reconciliation.reconcile(frappe.utils.nowdate(), frappe.utils.nowdate(), [payment])
		self.assertEqual([r["status"] for r in rows if r["payment_id"] == pid], [reconciliation.MATCHED])

	def test_partial_amount_records_nothing(self):
		ids = payments.create_pending_cart_for(self.items())["donation_ids"]
		pid, payment = cart_payment(ids, 30000)  # only the first line
		self.assertEqual(payments.verify_and_record_payment(pid, payment).reason, "amount_mismatch")
		self.assertEqual({frappe.db.get_value("Donation", n, "docstatus") for n in ids}, {0})

	def test_bank_transfer_creates_drafts_with_the_receipt(self):
		account = _bank_account()
		res = payments.submit_bank_transfer_for(
			self.items(), account, "receipt.png", "data:image/png;base64," + PNG, "محوّل", "+966500007003"
		)
		self.assertEqual(res["amount"], 355.5)
		docs = [frappe.get_doc("Donation", n) for n in res["donation_ids"]]
		self.assertEqual({(d.docstatus, d.channel) for d in docs}, {(0, "Bank Transfer")})
		self.assertTrue(all(d.transfer_proof and d.transfer_proof == docs[0].transfer_proof for d in docs))
		self.assertTrue(frappe.db.get_value("File", {"file_url": docs[0].transfer_proof}, "is_private"))

	def test_bank_transfer_checks_account_and_file(self):
		account = _bank_account()
		with self.assertRaises(frappe.ValidationError):
			payments.submit_bank_transfer_for(self.items(), "NOT-AN-ACCOUNT", "r.png", PNG)
		with self.assertRaises(frappe.ValidationError):  # a .png that is not a PNG
			payments.submit_bank_transfer_for(
				self.items(), account, "r.png", base64.b64encode(b"MZ" * 40).decode()
			)
		with self.assertRaises(frappe.ValidationError):
			payments.submit_bank_transfer_for(self.items(), account, "r.exe", PNG)

	def test_catalog_hides_targets(self):
		row = next(p for p in catalog() if p["code"] == self.a)
		self.assertEqual(row["options"], [{"label": "سقيا", "amount": 100.0}])
		self.assertNotIn("target_amount", row)
		self.assertNotIn("progress_percent", row)


def _bank_account():
	iban = "SA9799000000000000000099"
	existing = frappe.db.get_value("Bank Account", {"iban": iban})
	if existing:
		return existing
	if not frappe.db.exists("Bank", "بنك الاختبار"):
		frappe.get_doc({"doctype": "Bank", "bank_name": "بنك الاختبار"}).insert(ignore_permissions=True)
	return (
		frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": "حساب الاختبار",
				"bank": "بنك الاختبار",
				"company": frappe.db.get_single_value("Ataa Settings", "company"),
				"account": frappe.db.get_single_value("Ataa Settings", "main_bank_account"),
				"is_company_account": 1,
				"iban": iban,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
