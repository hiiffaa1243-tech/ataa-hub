"""M1: project balances come only from the General Ledger (PRD §6.2, D2)."""

from frappe.tests import IntegrationTestCase

from ataa_hub.accounting import get_project_balance
from ataa_hub.constants import FUND_UNRESTRICTED
from ataa_hub.tests.factories import account, make_journal_entry, make_project, settings


class TestProjectBalance(IntegrationTestCase):
	def setUp(self):
		s = settings()
		self.restricted = s.restricted_income_account
		self.unrestricted = s.unrestricted_income_account
		self.expense = s.disbursement_expense_account
		self.bank = s.main_bank_account
		self.t_in = s.fund_transfers_in_account
		self.t_out = s.fund_transfers_out_account
		self.project = make_project(target=1000).name
		self.other = make_project().name

	def donate(self, amount, project=None, account=None):
		project = project or self.project
		return make_journal_entry(
			[(self.bank, amount, 0, project), (account or self.restricted, 0, amount, project)]
		)

	def spend(self, amount, project=None):
		project = project or self.project
		return make_journal_entry([(self.expense, amount, 0, project), (self.bank, 0, amount, project)])

	def test_new_project_is_zero(self):
		b = get_project_balance(self.project)
		self.assertEqual((b.balance, b.donation_income, b.available), (0, 0, 0))
		self.assertEqual(b.progress_percent, 0)

	def test_donation_raises_balance_and_progress(self):
		self.donate(250)
		b = get_project_balance(self.project)
		self.assertEqual((b.balance, b.donation_income, b.available), (250, 250, 250))
		self.assertEqual(b.progress_percent, 25)

	def test_expense_lowers_balance_but_not_progress(self):
		self.donate(400)
		self.spend(150)
		b = get_project_balance(self.project)
		self.assertEqual((b.balance, b.donation_income), (250, 400))

	def test_cancelled_entry_is_ignored(self):
		self.donate(100)
		je = self.donate(300)
		je.cancel()
		self.assertEqual(get_project_balance(self.project).balance, 100)

	def test_other_projects_are_not_mixed(self):
		self.donate(500, project=self.other)
		self.assertEqual(get_project_balance(self.project).balance, 0)
		self.assertEqual(get_project_balance(self.other).balance, 500)

	def test_balance_sheet_only_entries_do_not_count(self):
		# Moving money between two bank accounts, tagged with the project, is not income.
		make_journal_entry(
			[(account("Moyasar Clearing"), 80, 0, self.project), (self.bank, 0, 80, self.project)]
		)
		self.assertEqual(get_project_balance(self.project).balance, 0)

	def test_fund_transfer_moves_balance_between_projects(self):
		general = settings().general_project
		before = get_project_balance(general).balance  # GENERAL is shared by other tests
		self.donate(1000, project=general, account=self.unrestricted)
		make_journal_entry([(self.t_out, 300, 0, general), (self.t_in, 0, 300, self.project)])

		self.assertEqual(get_project_balance(general).balance - before, 700)
		target = get_project_balance(self.project)
		self.assertEqual(target.balance, 300)
		# A transfer is not a donation: progress toward the target is unchanged.
		self.assertEqual(target.donation_income, 0)

	def test_unrestricted_project_has_no_progress(self):
		project = make_project(fund_type=FUND_UNRESTRICTED).name
		self.assertIsNone(get_project_balance(project).progress_percent)
