"""Donation and disbursement rules from PRD sections 5.3, 6.5 and 11."""

import frappe
from frappe.model.workflow import WorkflowTransitionError, apply_workflow
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from ataa_hub.services import get_spendable_balance
from ataa_hub.tests.factories import make_project, make_user, paid_donation

PM = "test-pm@ataa.test"
PM_OTHER = "test-pm2@ataa.test"
ACCOUNTANT = "test-accountant@ataa.test"
EXECUTIVE = "test-ed@ataa.test"


def balance(project):
	return frappe.db.get_value(
		"Donation Project",
		project,
		["collected_amount", "disbursed_amount", "available_balance"],
		as_dict=True,
	)


class TestDonationRules(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_project("TSTDON-01")
		make_project("TSTDON-OFF", status="Closed")

	def test_paid_donation_raises_project_balance_and_refund_reverses_it(self):
		before = flt(balance("TSTDON-01").collected_amount)
		donation = paid_donation("TSTDON-01", 500)
		self.assertEqual(flt(balance("TSTDON-01").collected_amount), before + 500)

		donation.status = "Refunded"
		donation.refund_reason = "Donor asked for a refund"
		donation.save()
		self.assertEqual(flt(balance("TSTDON-01").collected_amount), before)

	def test_refund_requires_reason(self):
		donation = paid_donation("TSTDON-01", 100)
		donation.status = "Refunded"
		self.assertRaises(frappe.ValidationError, donation.save)

	def test_paid_donation_cannot_be_deleted(self):
		donation = paid_donation("TSTDON-01", 100)
		self.assertRaises(frappe.ValidationError, frappe.delete_doc, "Donation", donation.name)

	def test_paid_donation_amount_is_locked(self):
		donation = paid_donation("TSTDON-01", 100)
		donation.amount = 1
		self.assertRaises(frappe.ValidationError, donation.save)

	def test_paid_cannot_go_back_to_pending(self):
		donation = paid_donation("TSTDON-01", 100)
		donation.status = "Pending"
		self.assertRaises(frappe.ValidationError, donation.save)

	def test_inactive_project_rejects_donations(self):
		self.assertRaises(frappe.ValidationError, paid_donation, "TSTDON-OFF", 100)

	def test_manual_entry_is_bank_transfer_only(self):
		doc = frappe.get_doc(
			{"doctype": "Donation", "project": "TSTDON-01", "amount": 100, "channel": "Website"}
		)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_bank_transfer_needs_proof_before_paid(self):
		doc = frappe.get_doc(
			{"doctype": "Donation", "project": "TSTDON-01", "amount": 750, "channel": "Bank Transfer"}
		).insert()
		self.assertEqual(doc.status, "Pending")

		doc.status = "Paid"
		self.assertRaises(frappe.ValidationError, doc.save)

		doc.reload()
		before = flt(balance("TSTDON-01").collected_amount)
		doc.status = "Paid"
		doc.transfer_proof = "/files/fake-transfer-proof.png"
		doc.save()
		self.assertEqual(flt(balance("TSTDON-01").collected_amount), before + 750)


class TestDisbursementWorkflow(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(PM, "Project Manager")
		make_user(PM_OTHER, "Project Manager")
		make_user(ACCOUNTANT, "Donations Accountant")
		make_user(EXECUTIVE, "Executive Director")
		make_project("TSTDSB-01", manager=PM)
		make_project("TSTDSB-02", manager=PM_OTHER)
		paid_donation("TSTDSB-01", 10000)
		paid_donation("TSTDSB-02", 10000)

	def tearDown(self):
		frappe.set_user("Administrator")

	def new_request(self, amount, project="TSTDSB-01", user=PM):
		frappe.set_user(user)
		doc = frappe.get_doc(
			{
				"doctype": "Disbursement Request",
				"project": project,
				"amount": amount,
				"purpose": "Test purchase",
			}
		).insert()
		frappe.set_user("Administrator")
		return doc

	def act(self, doc, user, action):
		frappe.set_user(user)
		try:
			return apply_workflow(doc, action)
		finally:
			frappe.set_user("Administrator")

	def test_request_above_balance_is_blocked_on_submit(self):
		doc = self.new_request(999999)
		self.assertRaises(frappe.ValidationError, self.act, doc, PM, "Submit for Review")
		self.assertEqual(frappe.db.get_value("Disbursement Request", doc.name, "workflow_state"), "Draft")

	def test_full_cycle_balance_drops_only_when_disbursed(self):
		start = flt(balance("TSTDSB-01").available_balance)
		spendable = get_spendable_balance("TSTDSB-01")
		doc = self.new_request(1000)

		doc = self.act(doc, PM, "Submit for Review")
		self.assertEqual(flt(doc.available_balance_at_request), spendable)  # snapshot at request time
		doc = self.act(doc, ACCOUNTANT, "Accountant Approve")
		doc = self.act(doc, EXECUTIVE, "Approve")
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(flt(balance("TSTDSB-01").available_balance), start)  # approved, not paid out yet

		doc = self.act(doc, ACCOUNTANT, "Confirm Disbursement")
		self.assertEqual(doc.workflow_state, "Disbursed")
		self.assertIsNotNone(doc.disbursed_on)
		self.assertEqual(flt(balance("TSTDSB-01").available_balance), start - 1000)

	def test_approved_amounts_are_reserved(self):
		spendable = get_spendable_balance("TSTDSB-01")
		first = self.new_request(flt(spendable * 0.6, 2))
		second = self.new_request(flt(spendable * 0.6, 2))
		for doc in (first, second):
			doc = self.act(doc, PM, "Submit for Review")
			self.act(doc, ACCOUNTANT, "Accountant Approve")

		self.act(frappe.get_doc("Disbursement Request", first.name), EXECUTIVE, "Approve")
		# Together they would spend 120% of the balance: the second approval must fail.
		self.assertRaises(
			frappe.ValidationError,
			self.act,
			frappe.get_doc("Disbursement Request", second.name),
			EXECUTIVE,
			"Approve",
		)

	def test_rejection_requires_reason(self):
		doc = self.new_request(100)
		doc = self.act(doc, PM, "Submit for Review")
		doc = self.act(doc, ACCOUNTANT, "Accountant Approve")
		self.assertRaises(frappe.ValidationError, self.act, doc, EXECUTIVE, "Reject")

		frappe.set_user(EXECUTIVE)
		doc = frappe.get_doc("Disbursement Request", doc.name)
		doc.rejection_reason = "Not a priority"
		doc.save()
		frappe.set_user("Administrator")
		doc = self.act(doc, EXECUTIVE, "Reject")
		self.assertEqual(doc.workflow_state, "Rejected")

	def test_project_manager_cannot_approve(self):
		doc = self.new_request(100)
		doc = self.act(doc, PM, "Submit for Review")
		doc = self.act(doc, ACCOUNTANT, "Accountant Approve")
		self.assertRaises(WorkflowTransitionError, self.act, doc, PM, "Approve")

	def test_accountant_can_return_to_draft(self):
		doc = self.new_request(100)
		doc = self.act(doc, PM, "Submit for Review")
		doc = self.act(doc, ACCOUNTANT, "Return")
		self.assertEqual(doc.workflow_state, "Draft")

	def test_project_manager_sees_only_own_projects(self):
		frappe.set_user(PM)
		projects = frappe.get_list("Donation Project", pluck="name", limit_page_length=0)
		donations = frappe.get_list("Donation", fields=["project"], limit_page_length=0)
		frappe.set_user("Administrator")

		self.assertIn("TSTDSB-01", projects)
		self.assertNotIn("TSTDSB-02", projects)
		self.assertTrue(all(d.project != "TSTDSB-02" for d in donations))

	def test_project_manager_cannot_request_for_someone_elses_project(self):
		self.assertRaises(frappe.PermissionError, self.new_request, 100, "TSTDSB-02", PM)
