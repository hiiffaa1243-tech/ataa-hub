"""M2: a Donation posts exactly one Journal Entry, and cancelling reverses it (PRD §6.1, §13)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from ataa_hub.accounting import get_project_balance
from ataa_hub.constants import FUND_UNRESTRICTED, ROLE_PROFILES
from ataa_hub.donors import get_or_create_donor
from ataa_hub.tests.factories import (
	account,
	gl_lines,
	make_bank_donation,
	make_integration_donation,
	make_journal_entry,
	make_project,
	make_user,
	settings,
)


class TestDonationAccounting(IntegrationTestCase):
	def setUp(self):
		self.project = make_project(target=1000, impact_unit_label="وجبة", impact_units_per_sar=0.5).name

	def test_draft_posts_nothing(self):
		d = make_bank_donation(self.project, 200, submit=False)
		self.assertEqual(d.payment_status, "Awaiting Payment")
		self.assertFalse(d.journal_entry)
		self.assertEqual(get_project_balance(self.project).balance, 0)

	def test_submit_posts_one_journal_entry_with_project_on_both_lines(self):
		d = make_bank_donation(self.project, 250)
		self.assertEqual(d.payment_status, "Paid")
		self.assertEqual(frappe.db.count("Journal Entry", {"ataa_reference_name": d.name, "docstatus": 1}), 1)

		lines = gl_lines(d.journal_entry)
		self.assertEqual(len(lines), 2)
		debit, credit = lines
		self.assertEqual((debit.account, flt(debit.debit)), (account("Main Bank Account"), 250))
		self.assertEqual((credit.account, flt(credit.credit)), (settings().restricted_income_account, 250))
		self.assertEqual({debit.project, credit.project}, {self.project})

	def test_balance_and_progress_follow_the_ledger(self):
		make_bank_donation(self.project, 250)
		b = get_project_balance(self.project)
		self.assertEqual((b.balance, b.progress_percent), (250, 25))

	def test_general_fund_goes_to_unrestricted_income(self):
		general = settings().general_project
		d = make_bank_donation(general, 40)
		credit = next(line for line in gl_lines(d.journal_entry) if line.credit)
		self.assertEqual(credit.account, settings().unrestricted_income_account)
		self.assertEqual(d.fund_type, FUND_UNRESTRICTED)

	def test_channel_decides_debit_account(self):
		d = make_integration_donation(self.project, 90, channel="Online Store")
		debit = next(line for line in gl_lines(d.journal_entry) if line.debit)
		self.assertEqual(debit.account, account("Online Store Clearing"))

	def test_impact_is_frozen_at_submit(self):
		d = make_bank_donation(self.project, 100)
		self.assertEqual((d.impact_units, d.impact_unit_label), (50, "وجبة"))
		frappe.db.set_value("Project", self.project, "impact_units_per_sar", 2)
		self.assertEqual(frappe.db.get_value("Donation", d.name, "impact_units"), 50)

	def test_receipt_token_is_unguessable_and_unique(self):
		a, b = make_bank_donation(self.project, 10), make_bank_donation(self.project, 10)
		self.assertEqual(len(a.receipt_token), 32)
		self.assertNotEqual(a.receipt_token, b.receipt_token)

	# ------------------------------------------------------------ cancellation

	def test_cancel_needs_a_reason(self):
		d = make_bank_donation(self.project, 100)
		with self.assertRaises(frappe.ValidationError):
			d.cancel()

	def test_cancel_reverses_the_ledger(self):
		d = make_bank_donation(self.project, 300)
		d.cancel_reason = "Duplicate bank entry"
		d.save()
		d.cancel()

		self.assertEqual(frappe.db.get_value("Journal Entry", d.journal_entry, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Donation", d.name, "payment_status"), "Refunded")
		self.assertEqual(get_project_balance(self.project).balance, 0)

	def test_journal_entry_cannot_be_cancelled_on_its_own(self):
		d = make_bank_donation(self.project, 100)
		je = frappe.get_doc("Journal Entry", d.journal_entry)
		with self.assertRaises(frappe.ValidationError):
			je.cancel()

	def test_received_donation_cannot_be_deleted(self):
		d = make_bank_donation(self.project, 100)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Donation", d.name, ignore_permissions=True)

	# --------------------------------------------------------------- validation

	def test_bank_transfer_needs_proof_to_submit(self):
		d = make_bank_donation(self.project, 100, submit=False, proof=None)
		with self.assertRaises(frappe.ValidationError):
			d.submit()

	def test_manual_entry_is_bank_transfer_only(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Donation", "project": self.project, "amount": 10, "channel": "Online Store"}
			).insert()

	def test_amount_must_be_positive(self):
		with self.assertRaises(frappe.ValidationError):
			make_bank_donation(self.project, 0, submit=False)

	def test_closed_or_private_project_rejects_donations(self):
		closed = make_project(status="Completed").name
		private = make_project(is_public=0).name
		for project in (closed, private):
			with self.assertRaises(frappe.ValidationError):
				make_bank_donation(project, 10, submit=False)

	def test_pos_needs_terminal_fields(self):
		with self.assertRaises(frappe.ValidationError):
			make_integration_donation(self.project, 10, channel="POS", submit=False, terminal_id="T01")
		d = make_integration_donation(
			self.project, 10, channel="POS", terminal_id="T01", card_scheme="mada", rrn="123456789012"
		)
		debit = next(line for line in gl_lines(d.journal_entry) if line.debit)
		self.assertEqual(debit.account, account("mada POS Clearing"))

	def test_idempotency_key_is_unique_in_the_database(self):
		make_integration_donation(self.project, 10, idempotency_key="store:ORDER-1", submit=False)
		with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
			make_integration_donation(self.project, 10, idempotency_key="store:ORDER-1", submit=False)

	def test_manual_journal_on_donation_income_needs_project(self):
		with self.assertRaises(frappe.ValidationError):
			make_journal_entry(
				[
					(account("Main Bank Account"), 50, 0, None),
					(settings().restricted_income_account, 0, 50, None),
				]
			)


class TestDonors(IntegrationTestCase):
	def setUp(self):
		self.project = make_project().name

	def test_returning_donor_matched_by_mobile(self):
		first = get_or_create_donor("Test Donor", "+966 50 000 1234", "donor@example.test")
		second = get_or_create_donor("Other Name", "+966500001234")
		self.assertEqual(first, second)
		customer = frappe.get_doc("Customer", first)
		self.assertEqual((customer.customer_group, customer.donor_mobile), ("Donors", "+966500001234"))
		contact = frappe.get_doc("Contact", customer.customer_primary_contact)
		self.assertEqual(contact.links[0].link_name, first)
		self.assertEqual(contact.email_id, "donor@example.test")

	def test_anonymous_creates_no_customer(self):
		self.assertIsNone(get_or_create_donor("Someone", None))

	def test_lifetime_giving_follows_submit_and_cancel(self):
		donor = get_or_create_donor("Giver", "+966500004321")
		make_bank_donation(self.project, 100, donor=donor)
		d = make_bank_donation(self.project, 50, donor=donor)
		self.assertEqual(frappe.db.get_value("Customer", donor, "lifetime_giving"), 150)

		d.cancel_reason = "Refund requested"
		d.save()
		d.cancel()
		self.assertEqual(frappe.db.get_value("Customer", donor, "lifetime_giving"), 100)


class TestProjectManagerRows(IntegrationTestCase):
	def test_project_manager_sees_only_assigned_projects_and_their_donations(self):
		pm = make_user("pm-rows@ataa.test", ["Project Manager"])
		mine = make_project(users=[{"user": pm, "welcome_email_sent": 1}]).name
		theirs = make_project().name
		mine_donation = make_bank_donation(mine, 10).name
		their_donation = make_bank_donation(theirs, 10).name

		frappe.set_user(pm)
		try:
			projects = set(frappe.get_list("Project", pluck="name"))
			donations = set(frappe.get_list("Donation", pluck="name"))
			self.assertIn(mine, projects)
			self.assertNotIn(theirs, projects)
			self.assertIn(mine_donation, donations)
			self.assertNotIn(their_donation, donations)
			self.assertFalse(frappe.get_doc("Donation", their_donation).has_permission("read"))
		finally:
			frappe.set_user("Administrator")

	def test_other_roles_are_not_restricted_by_the_row_rule(self):
		"""Frappe v16: a has_permission hook returning None would deny everyone else."""
		accountant = make_user("acc-rows@ataa.test", ROLE_PROFILES["Ataa Accountant"])
		project = make_project().name
		donation = make_bank_donation(project, 10).name
		frappe.set_user(accountant)
		try:
			self.assertTrue(frappe.get_doc("Donation", donation).has_permission("read"))
			self.assertTrue(frappe.get_doc("Project", project).has_permission("read"))
			self.assertFalse(frappe.get_doc("Project", project).has_permission("write"))  # read-only
		finally:
			frappe.set_user("Administrator")
