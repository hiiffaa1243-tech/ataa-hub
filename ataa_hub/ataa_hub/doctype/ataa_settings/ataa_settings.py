import frappe
from frappe import _
from frappe.model.document import Document


class AtaaSettings(Document):
	def validate(self):
		# Every account must belong to the selected company.
		for field in (
			"restricted_income_account",
			"unrestricted_income_account",
			"disbursement_expense_account",
			"fund_transfers_in_account",
			"fund_transfers_out_account",
			"main_bank_account",
		):
			account = self.get(field)
			if account and frappe.db.get_value("Account", account, "company") != self.company:
				frappe.throw(
					_("الحساب {0} لا يتبع الشركة {1}.").format(
						frappe.bold(account), frappe.bold(self.company)
					)
				)


def get_settings():
	"""Cached Ataa Settings. Read-only use; call frappe.get_single to edit."""
	return frappe.get_cached_doc("Ataa Settings")
