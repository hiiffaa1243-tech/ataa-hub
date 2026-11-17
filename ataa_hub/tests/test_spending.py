"""M4: governed spending (PRD §6.3, §7.8, §7.9, §13).

Every workflow step is run as the user who owns it (Project Manager, Accountant,
Executive Director) through Frappe's own `apply_workflow`, so role rules are tested too.
Amounts are always compared against the General Ledger.
"""

import frappe
from frappe.model.workflow import WorkflowPermissionError, apply_workflow
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from ataa_hub.accounting import get_available, get_project_balance
from ataa_hub.constants import ROLE_ACCOUNTANT, ROLE_EXECUTIVE, ROLE_PROJECT_MANAGER
from ataa_hub.tests.factories import gl_lines, make_bank_donation, make_project, make_user, settings

PM = "pm-spend@ataa.test"
ACC = "acc-spend@ataa.test"
ED = "ed-spend@ataa.test"


def act(doc, action, user):
	frappe.set_user(user)
	try:
		return apply_workflow(doc, action)
	finally:
		frappe.set_user("Administrator")


class SpendingTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(PM, [ROLE_PROJECT_MANAGER])
		make_user(ACC, [ROLE_ACCOUNTANT])
		make_user(ED, [ROLE_EXECUTIVE])

	def tearDown(self):
		frappe.set_user("Administrator")

	def funded_project(self, donations=1000, **kw):
		project = make_project(users=[{"user": PM, "welcome_email_sent": 1}], **kw).name
		if donations:
			make_bank_donation(project, donations)
		return project

	def request(self, project, amount, purpose="Water coolers"):
		frappe.set_user(PM)
		try:
			return frappe.get_doc(
				{"doctype": "Disbursement Request", "project": project, "amount": amount, "purpose": purpose}
			).insert()
		finally:
			frappe.set_user("Administrator")

	def approve(self, doc):
		doc = act(doc, "Submit for Review", PM)
		doc = act(doc, "Approve", ACC)
		return act(doc, "Approve", ED)

	def pay(self, doc):
		return act(doc, "Mark Paid", ACC)


class TestDisbursement(SpendingTestCase):
	def test_full_path_posts_one_journal_entry(self):
		project = self.funded_project(1000)
		doc = self.request(project, 600)
		self.assertEqual(doc.workflow_state, "Draft")

		doc = act(doc, "Submit for Review", PM)
		self.assertEqual(
			(doc.workflow_state, flt(doc.available_balance_at_request)), ("Pending Accountant Review", 1000)
		)
		doc = act(doc, "Approve", ACC)
		doc = act(doc, "Approve", ED)
		self.assertEqual((doc.workflow_state, doc.docstatus), ("Approved", 1))

		b = get_project_balance(project)
		self.assertEqual((b.balance, b.committed, b.available), (1000, 600, 400))

		doc = self.pay(doc)
		doc.reload()
		self.assertEqual(doc.workflow_state, "Paid")
		self.assertTrue(doc.paid_on)
		lines = gl_lines(doc.journal_entry)
		self.assertEqual(
			{(line.account, flt(line.debit), flt(line.credit), line.project) for line in lines},
			{
				(settings().disbursement_expense_account, 600, 0, project),
				(settings().main_bank_account, 0, 600, project),
			},
		)
		b = get_project_balance(project)
		self.assertEqual((b.balance, b.committed, b.available, b.donation_income), (400, 0, 400, 1000))

	def test_overspend_blocked_when_sent_for_review(self):
		doc = self.request(self.funded_project(1000), 1500)
		with self.assertRaises(frappe.ValidationError):
			act(doc, "Submit for Review", PM)

	def test_approved_money_is_committed_for_other_requests(self):
		project = self.funded_project(1000)
		first, second = self.request(project, 600), self.request(project, 600)
		second = act(second, "Submit for Review", PM)  # 600 ≤ 1000: fine at this moment
		self.approve(first)  # now 600 of 1000 is committed

		with self.assertRaises(frappe.ValidationError):
			act(second, "Approve", ACC)

	def test_blocked_at_executive_approval(self):
		project = self.funded_project(1000)
		doc = act(act(self.request(project, 800), "Submit for Review", PM), "Approve", ACC)
		self.approve(self.request(project, 500))
		with self.assertRaises(frappe.ValidationError):
			act(doc, "Approve", ED)

	def test_blocked_at_payment_if_money_left(self):
		project = self.funded_project(0)
		donation = make_bank_donation(project, 1000)
		doc = self.approve(self.request(project, 600))
		donation.cancel_reason = "Bounced transfer"
		donation.save()
		donation.cancel()
		with self.assertRaises(frappe.ValidationError):
			self.pay(doc)

	def test_reject_needs_reason(self):
		doc = act(act(self.request(self.funded_project(), 100), "Submit for Review", PM), "Approve", ACC)
		with self.assertRaises(frappe.ValidationError):
			act(doc, "Reject", ED)
		doc.reload()
		doc.rejection_reason = "Not in this year's plan"
		doc.save()
		self.assertEqual(act(doc, "Reject", ED).workflow_state, "Rejected")

	def test_accountant_can_return_to_draft(self):
		doc = act(self.request(self.funded_project(), 100), "Submit for Review", PM)
		self.assertEqual(act(doc, "Return", ACC).workflow_state, "Draft")

	def test_each_step_belongs_to_one_role(self):
		doc = act(self.request(self.funded_project(), 100), "Submit for Review", PM)
		with self.assertRaises(WorkflowPermissionError):
			act(doc, "Approve", PM)  # a PM cannot approve their own request
		doc = act(doc, "Approve", ACC)
		with self.assertRaises(WorkflowPermissionError):
			act(doc, "Approve", ACC)  # executive step

	def test_cancelling_payment_journal_returns_to_approved(self):
		project = self.funded_project(1000)
		doc = self.pay(self.approve(self.request(project, 300)))
		doc.reload()
		first_je = doc.journal_entry

		frappe.get_doc("Journal Entry", first_je).cancel()  # e.g. paid from the wrong bank
		doc.reload()
		self.assertEqual((doc.workflow_state, doc.journal_entry, doc.paid_on), ("Approved", None, None))
		b = get_project_balance(project)
		self.assertEqual((b.balance, b.committed), (1000, 300))

		doc = self.pay(doc)
		doc.reload()
		self.assertNotEqual(doc.journal_entry, first_je)
		self.assertEqual(get_project_balance(project).balance, 700)

	def test_paid_request_cannot_be_cancelled_before_its_journal(self):
		doc = self.pay(self.approve(self.request(self.funded_project(), 100)))
		doc.reload()
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()

	def test_expense_account_must_be_an_expense(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Disbursement Request",
					"project": self.funded_project(),
					"amount": 10,
					"purpose": "x",
					"expense_account": settings().restricted_income_account,
				}
			).insert()

	def test_project_manager_sees_only_own_requests(self):
		mine = self.request(self.funded_project(), 10).name
		other_project = make_project().name
		frappe.set_user(PM)
		try:
			self.assertIn(mine, frappe.get_list("Disbursement Request", pluck="name"))
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc(
					{
						"doctype": "Disbursement Request",
						"project": other_project,
						"amount": 10,
						"purpose": "x",
					}
				).insert()
		finally:
			frappe.set_user("Administrator")


class TestFundAllocation(SpendingTestCase):
	def allocation(self, to_project, amount, user=ACC):
		frappe.set_user(user)
		try:
			return frappe.get_doc(
				{
					"doctype": "Fund Allocation",
					"to_project": to_project,
					"amount": amount,
					"reason": "Ramadan gap",
				}
			).insert()
		finally:
			frappe.set_user("Administrator")

	def test_allocation_unblocks_a_restricted_request(self):
		general = settings().general_project
		make_bank_donation(general, 500)
		general_before = get_available(general, lock=False)
		project = self.funded_project(0)

		blocked = self.request(project, 300)
		with self.assertRaises(frappe.ValidationError):
			act(blocked, "Submit for Review", PM)

		fal = act(self.allocation(project, 300), "Request", ACC)
		self.assertEqual(flt(fal.available_at_request), general_before)
		fal = act(fal, "Approve", ED)
		self.assertEqual(fal.docstatus, 1)
		self.assertEqual(
			{(line.project, flt(line.debit), flt(line.credit)) for line in gl_lines(fal.journal_entry)},
			{(general, 300, 0), (project, 0, 300)},
		)
		self.assertEqual(get_available(general, lock=False), general_before - 300)
		b = get_project_balance(project)
		self.assertEqual((b.balance, b.donation_income), (300, 0))  # progress is donations only

		doc = self.pay(self.approve(self.request(project, 300)))
		self.assertEqual(doc.workflow_state, "Paid")
		self.assertEqual(get_project_balance(project).balance, 0)

	def test_cannot_allocate_more_than_general_available(self):
		general = settings().general_project
		too_much = get_available(general, lock=False) + 1
		with self.assertRaises(frappe.ValidationError):
			act(self.allocation(self.funded_project(0), too_much), "Request", ACC)

	def test_checked_again_at_approval(self):
		general = settings().general_project
		make_bank_donation(general, 100)
		available = get_available(general, lock=False)
		first = act(self.allocation(self.funded_project(0), available), "Request", ACC)
		second = act(self.allocation(self.funded_project(0), available, user=PM), "Request", PM)
		act(first, "Approve", ED)
		with self.assertRaises(frappe.ValidationError):
			act(second, "Approve", ED)

	def test_only_unrestricted_to_restricted(self):
		restricted = self.funded_project(100)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Fund Allocation",
					"from_project": restricted,
					"to_project": self.funded_project(0),
					"amount": 10,
					"reason": "x",
				}
			).insert()
		with self.assertRaises(frappe.ValidationError):
			self.allocation(settings().general_project, 10)

	def test_cancel_reverses_and_journal_cannot_be_cancelled_alone(self):
		general = settings().general_project
		make_bank_donation(general, 200)
		project = self.funded_project(0)
		fal = act(act(self.allocation(project, 150), "Request", ACC), "Approve", ED)

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Journal Entry", fal.journal_entry).cancel()

		fal.reload()
		fal.cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", fal.journal_entry, "docstatus"), 2)
		self.assertEqual(get_project_balance(project).balance, 0)
