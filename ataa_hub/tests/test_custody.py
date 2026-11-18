"""Custody (عهدة) and the staff dashboard.

request (PM) → approve & pay (Accountant, JE Dr custody / Cr bank, amount held back)
→ purchases with invoices (PM) → auto "Closing Requested" when spent in full
→ close (Accountant, JE Dr expense + Dr bank (cash back) / Cr custody, PDF report)
"""

import shutil

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from ataa_hub import custody, staff_dashboard
from ataa_hub.accounting import get_project_balance
from ataa_hub.constants import ROLE_PROFILES
from ataa_hub.tests.factories import gl_lines, make_bank_donation, make_project, make_user, settings, unique

PM = "pm-custody@ataa.test"
PM2 = "pm2-custody@ataa.test"
ACC = "acc-custody@ataa.test"
ED = "ed-custody@ataa.test"

PNG = (
	b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
	b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def as_user(user, fn, *args, **kw):
	frappe.set_user(user)
	try:
		return fn(*args, **kw)
	finally:
		frappe.set_user("Administrator")


def invoice_file():
	f = frappe.get_doc(
		{"doctype": "File", "file_name": f"{unique('inv')}.png", "content": PNG, "is_private": 1}
	).insert(ignore_permissions=True)
	return f.file_url


class TestCustody(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(PM, ROLE_PROFILES["Ataa Project Manager"])
		make_user(PM2, ROLE_PROFILES["Ataa Project Manager"])
		make_user(ACC, ROLE_PROFILES["Ataa Accountant"])
		make_user(ED, ROLE_PROFILES["Ataa Executive Director"])

	def tearDown(self):
		frappe.set_user("Administrator")

	def funded(self, amount=1000):
		project = make_project(users=[{"user": PM, "welcome_email_sent": 1}]).name
		make_bank_donation(project, amount)
		return project

	def request(self, project, amount=300):
		name = as_user(PM, staff_dashboard.create_custody, project, amount, "Cleaning supplies")
		return frappe.get_doc("Custody", name)

	def add_purchases(self, name, *amounts, invoice=True):
		def run():
			doc = frappe.get_doc("Custody", name)
			for a in amounts:
				doc.append(
					"expenses",
					{"description": f"Item {a}", "amount": a, "invoice": invoice_file() if invoice else None},
				)
			doc.save()
			return doc

		return as_user(PM, run)

	def test_full_cycle_books_the_money_and_attaches_a_report(self):
		project = self.funded(1000)
		doc = self.request(project, 300)
		self.assertEqual((doc.status, doc.holder), ("Requested", PM))
		self.assertEqual(get_project_balance(project).available, 1000)  # nothing held before payment

		as_user(ACC, custody.approve_and_pay, doc.name)
		doc.reload()
		self.assertEqual(doc.status, "Open")
		s = settings()
		self.assertEqual(
			{(r.account, flt(r.debit), flt(r.credit)) for r in gl_lines(doc.pay_journal_entry)},
			{(s.custody_account, 300, 0), (s.main_bank_account, 0, 300)},
		)
		b = get_project_balance(project)
		self.assertEqual((b.balance, b.committed, b.available), (1000, 300, 700))

		doc = self.add_purchases(doc.name, 120, 80.5)
		self.assertEqual((doc.spent, doc.remaining, doc.status), (200.5, 99.5, "Open"))

		as_user(PM, custody.request_close, doc.name)
		as_user(ACC, custody.close, doc.name)
		doc.reload()
		self.assertEqual((doc.status, doc.closed_by), ("Closed", ACC))
		self.assertEqual(
			{(r.account, flt(r.debit), flt(r.credit)) for r in gl_lines(doc.close_journal_entry)},
			{
				(s.disbursement_expense_account, 200.5, 0),
				(s.main_bank_account, 99.5, 0),
				(s.custody_account, 0, 300),
			},
		)
		b = get_project_balance(project)
		self.assertEqual((b.balance, b.committed, b.available), (799.5, 0, 799.5))
		if shutil.which("wkhtmltopdf"):  # CI has no PDF engine; the close still books the GL
			self.assertTrue(doc.report_file and doc.report_file.endswith(".pdf"))

	def test_spending_it_all_asks_the_accountant_to_close(self):
		doc = self.request(self.funded(), 100)
		as_user(ACC, custody.approve_and_pay, doc.name)
		doc = self.add_purchases(doc.name, 60, 40)
		doc.reload()
		self.assertEqual(doc.status, "Closing Requested")
		self.assertTrue(
			frappe.db.exists(
				"Notification Log",
				{"for_user": ACC, "document_name": doc.name, "subject": ("like", "%إقفال%")},
			)
		)

	def test_purchases_cannot_exceed_the_custody(self):
		doc = self.request(self.funded(), 100)
		as_user(ACC, custody.approve_and_pay, doc.name)
		self.assertRaises(frappe.ValidationError, self.add_purchases, doc.name, 150)

	def test_no_purchases_before_payment_and_no_status_edits(self):
		doc = self.request(self.funded(), 100)
		self.assertRaises(frappe.ValidationError, self.add_purchases, doc.name, 10)

		def tamper():
			d = frappe.get_doc("Custody", doc.name)
			d.status = "Open"
			d.save()

		self.assertRaises(frappe.ValidationError, as_user, PM, tamper)

	def test_close_needs_an_invoice_on_every_line(self):
		doc = self.request(self.funded(), 100)
		as_user(ACC, custody.approve_and_pay, doc.name)
		self.add_purchases(doc.name, 30, invoice=False)
		self.assertRaises(frappe.ValidationError, as_user, ACC, custody.close, doc.name)

	def test_cannot_pay_more_than_available(self):
		doc = self.request(self.funded(100), 500)
		self.assertRaises(frappe.ValidationError, as_user, ACC, custody.approve_and_pay, doc.name)

	def test_only_the_accountant_pays_and_closes(self):
		doc = self.request(self.funded(), 100)
		self.assertRaises(frappe.PermissionError, as_user, PM, custody.approve_and_pay, doc.name)
		self.assertRaises(frappe.PermissionError, as_user, ED, custody.approve_and_pay, doc.name)
		as_user(ACC, custody.reject, doc.name, "Not needed")
		self.assertEqual(
			frappe.db.get_value("Custody", doc.name, ["status", "reject_reason"]), ("Rejected", "Not needed")
		)

	def test_project_managers_see_only_their_projects_custody(self):
		doc = self.request(self.funded(), 50)
		names = as_user(PM2, frappe.get_list, "Custody", pluck="name")
		self.assertNotIn(doc.name, names)
		self.assertIn(doc.name, as_user(PM, frappe.get_list, "Custody", pluck="name"))
		self.assertFalse(as_user(PM2, frappe.has_permission, "Custody", "read", doc.name))

	def test_report_embeds_invoice_images(self):
		url = invoice_file()
		self.assertTrue(custody.invoice_data_uri(url).startswith("data:image/png;base64,"))
		self.assertIsNone(custody.invoice_data_uri(None))


class TestStaffDashboard(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(PM, ROLE_PROFILES["Ataa Project Manager"])
		make_user(PM2, ROLE_PROFILES["Ataa Project Manager"])
		make_user(ACC, ROLE_PROFILES["Ataa Accountant"])
		make_user(ED, ROLE_PROFILES["Ataa Executive Director"])

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_each_role_gets_its_own_view(self):
		self.assertEqual(as_user(PM, staff_dashboard.get_dashboard)["view"], "pm")
		self.assertEqual(as_user(ACC, staff_dashboard.get_dashboard)["view"], "accountant")
		ed = as_user(ED, staff_dashboard.get_dashboard)
		self.assertEqual(ed["view"], "executive")
		self.assertIn("approvals", ed)

	def test_pm_sees_only_own_projects_with_targets(self):
		mine = make_project(users=[{"user": PM, "welcome_email_sent": 1}], target=5000).name
		make_bank_donation(mine, 1250)
		other = make_project(users=[{"user": PM2, "welcome_email_sent": 1}]).name
		d = as_user(PM, staff_dashboard.get_dashboard)
		names = {p["name"]: p for p in d["projects"]}
		self.assertIn(mine, names)
		self.assertNotIn(other, names)
		self.assertEqual(
			(names[mine]["target"], names[mine]["collected"], names[mine]["progress"]), (5000, 1250, 25)
		)

	def test_add_project_dialog_creates_a_project_the_pm_can_see(self):
		code = unique("NEW")
		name = as_user(
			PM,
			staff_dashboard.create_project,
			{
				"project_name": "Test well",
				"project_code": code.lower(),
				"fund_type": "Restricted",
				"target_amount": 9000,
				"is_public": 1,
				"options": [{"label": "Share", "amount": 50}, {"label": "", "amount": 10}],
			},
		)
		p = frappe.get_doc("Project", name)
		self.assertEqual((p.project_code, p.target_amount, len(p.donation_options)), (code, 9000, 1))
		self.assertIn(name, {r["name"] for r in as_user(PM, staff_dashboard.get_dashboard)["projects"]})
		self.assertRaises(
			frappe.PermissionError,
			as_user,
			ACC,
			staff_dashboard.create_project,
			{"project_name": "x", "project_code": unique("X"), "fund_type": "Restricted"},
		)

	def test_request_dialog_sends_to_accountant_and_ed_approves_from_dashboard(self):
		project = make_project(users=[{"user": PM, "welcome_email_sent": 1}]).name
		make_bank_donation(project, 1000)
		name = as_user(PM, staff_dashboard.create_disbursement_request, project, 200, "Chairs")
		self.assertEqual(
			frappe.db.get_value("Disbursement Request", name, "workflow_state"), "Pending Accountant Review"
		)
		as_user(ACC, staff_dashboard.apply_action, "Disbursement Request", name, "Approve")
		self.assertIn(name, {r.name for r in as_user(ED, staff_dashboard.get_dashboard)["approvals"]})
		self.assertEqual(
			as_user(ED, staff_dashboard.apply_action, "Disbursement Request", name, "Approve"), "Approved"
		)
		self.assertRaises(
			frappe.ValidationError, as_user, ED, staff_dashboard.apply_action, "Donation", name, "Approve"
		)
