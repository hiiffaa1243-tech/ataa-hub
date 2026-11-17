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


def get_committed_amount(project: str, exclude_request: str | None = None) -> float:
	"""Approved disbursements not yet paid (they leave the balance only when paid)."""
	dr = frappe.qb.DocType("Disbursement Request")
	query = (
		frappe.qb.from_(dr)
		.select(Sum(dr.amount))
		.where((dr.project == project) & (dr.docstatus == 1) & (dr.workflow_state == "Approved"))
	)
	if exclude_request:
		query = query.where(dr.name != exclude_request)
	return flt(query.run()[0][0])


def lock_project(project: str) -> None:
	"""Row lock on the project until the transaction ends.

	Every spending check takes this lock first, so two approvals on the same project
	run one after the other and can never spend the same riyal twice (PRD §6.3).
	"""
	frappe.db.sql("select name from `tabProject` where name = %s for update", (project,))


def get_available(project: str, exclude_request: str | None = None, lock: bool = True) -> float:
	if lock:
		lock_project(project)
	return flt(_pl_sum(project) - get_committed_amount(project, exclude_request), 2)


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


@frappe.whitelist()
def get_project_balance_for_form(project: str) -> dict:
	"""Shown on the Disbursement Request / Fund Allocation forms."""
	frappe.has_permission("Project", "read", project, throw=True)
	return get_project_balance(project)
