"""Project balances, read from the General Ledger (PRD §6.2, decision D2).

The GL is the single source of truth for money: nothing here is stored, every
number is a SUM over submitted, non-cancelled GL Entries tagged with the project.

    balance(P)   = Σ(credit − debit) on Income and Expense accounts for project P
    committed(P) = approved, not yet paid Disbursement Requests of P
    available(P) = balance(P) − committed(P)
    progress(P)  = donation income of P ÷ target_amount
"""

import frappe
from frappe.query_builder.functions import Coalesce, Sum
from frappe.utils import flt


def _pl_sum(project: str, accounts: list[str] | None = None) -> float:
	"""Σ(credit − debit) for the project on P&L accounts (optionally only `accounts`)."""
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	query = (
		frappe.qb.from_(gle)
		.join(account)
		.on(account.name == gle.account)
		.select(Coalesce(Sum(gle.credit - gle.debit), 0))
		.where(gle.project == project)
		.where(gle.is_cancelled == 0)
		.where(account.root_type.isin(["Income", "Expense"]))
	)
	if accounts is not None:
		if not accounts:
			return 0.0
		query = query.where(gle.account.isin(accounts))
	return flt(query.run()[0][0])


def get_committed_amount(project: str) -> float:
	"""Approved disbursements not yet paid. The DocType arrives in M4; until then 0."""
	if not frappe.db.table_exists("Disbursement Request"):
		return 0.0
	return flt(
		frappe.db.get_value(
			"Disbursement Request",
			{"project": project, "docstatus": 1, "workflow_state": "Approved"},
			"sum(amount)",
		)
	)


def get_donation_income_accounts() -> list[str]:
	settings = frappe.get_cached_doc("Ataa Settings")
	return [a for a in (settings.restricted_income_account, settings.unrestricted_income_account) if a]


def get_project_balance(project: str) -> frappe._dict:
	"""Everything a dashboard, API response, portal page or event screen needs about a project's money."""
	balance = _pl_sum(project)
	donations = _pl_sum(project, get_donation_income_accounts())
	committed = get_committed_amount(project)
	target = flt(frappe.db.get_value("Project", project, "target_amount"))
	return frappe._dict(
		balance=balance,
		donation_income=donations,
		committed=committed,
		available=balance - committed,
		target_amount=target,
		progress_percent=flt(donations / target * 100, 2) if target else None,
	)
