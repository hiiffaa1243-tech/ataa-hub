"""Small builders for test data. Fake data only."""

import frappe
from frappe.utils import nowdate

from ataa_hub.constants import FUND_RESTRICTED


def settings():
	return frappe.get_single("Ataa Settings")


def company():
	return settings().company


def cost_center():
	return frappe.get_cached_value("Company", company(), "cost_center")


def unique(prefix="T"):
	return f"{prefix}-{frappe.generate_hash(length=6).upper()}"


def make_project(code=None, fund_type=FUND_RESTRICTED, target=10000, **extra):
	code = code or unique("PRJ")
	existing = frappe.db.get_value("Project", {"project_code": code}, "name")
	if existing:
		return frappe.get_doc("Project", existing)
	return frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": f"Test project {code}",
			"project_code": code,
			"company": company(),
			"status": "Open",
			"is_active": "Yes",
			"fund_type": fund_type,
			"target_amount": target if fund_type == FUND_RESTRICTED else 0,
			"is_public": 1,
			**extra,
		}
	).insert(ignore_permissions=True)


def make_journal_entry(lines, submit=True):
	"""lines: [(account, debit, credit, project_or_None), ...]"""
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"company": company(),
			"posting_date": nowdate(),
			"voucher_type": "Journal Entry",
			"user_remark": "Ataa Hub test entry",
			"accounts": [
				{
					"account": account,
					"debit_in_account_currency": debit,
					"credit_in_account_currency": credit,
					"project": project,
					"cost_center": cost_center(),
				}
				for account, debit, credit, project in lines
			],
		}
	)
	je.insert(ignore_permissions=True)
	if submit:
		je.submit()
	return je


def account(account_name):
	"""Full account name in the test company, e.g. account("Moyasar Clearing")."""
	return frappe.db.get_value(
		"Account", {"company": company(), "account_name": account_name, "is_group": 0}, "name"
	)
