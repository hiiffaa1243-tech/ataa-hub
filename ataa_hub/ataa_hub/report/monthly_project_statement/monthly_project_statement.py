"""Monthly Project Statement (PRD §10): replaces the association's monthly Excel.

Per project, straight from the General Ledger (the single source of truth):
opening balance, donation income, membership income, transfers in / out,
expenses, and closing balance. balance = Σ(credit − debit) on P&L accounts,
the same rule as accounting.get_project_balance, so the report always agrees
with the API, the portal and the spending checks.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt, get_first_day, get_last_day, getdate, nowdate

CATEGORIES = ("donations", "memberships", "transfers_in", "transfers_out", "expenses", "other")


def execute(filters=None):
	f = frappe._dict(filters or {})
	from_date = getdate(f.from_date or get_first_day(nowdate()))
	to_date = getdate(f.to_date or get_last_day(nowdate()))
	category_of = _account_categories()

	opening = _sums(f, None, from_date, exclusive_end=True)
	period = _sums(f, from_date, to_date)

	projects = frappe.get_all(
		"Project",
		filters={"name": f.project} if f.project else {"fund_type": ("is", "set")},
		fields=["name", "project_name", "fund_type"],
		order_by="fund_type desc, project_name asc",
	)
	rows = []
	for p in projects:
		row = {"project": p.name, "project_title": p.project_name, "fund_type": p.fund_type}
		row["opening"] = sum(v for (proj, _acc), v in opening.items() if proj == p.name)
		for c in CATEGORIES:
			row[c] = 0.0
		for (proj, account), value in period.items():
			if proj == p.name:
				row[category_of(account)] += value
		# Show outflows as positive numbers; the closing balance uses signed values.
		net = sum(row[c] for c in CATEGORIES)
		row["transfers_out"] = -row["transfers_out"]
		row["expenses"] = -row["expenses"]
		row["closing"] = flt(row["opening"] + net, 2)
		if any(flt(row[k]) for k in ("opening", "closing", *CATEGORIES)) or f.project:
			rows.append(row)

	columns = [
		{
			"fieldname": "project",
			"label": _("Project"),
			"fieldtype": "Link",
			"options": "Project",
			"width": 120,
		},
		{"fieldname": "project_title", "label": _("Project Title"), "fieldtype": "Data", "width": 200},
		{"fieldname": "fund_type", "label": _("Fund Type"), "fieldtype": "Data", "width": 110},
		{"fieldname": "opening", "label": _("Opening Balance"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "donations", "label": _("Donations"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "memberships", "label": _("Memberships"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "transfers_in", "label": _("Transfers In"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "transfers_out", "label": _("Transfers Out"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "expenses", "label": _("Expenses"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "other", "label": _("Other"), "fieldtype": "Currency", "width": 100},
		{"fieldname": "closing", "label": _("Closing Balance"), "fieldtype": "Currency", "width": 140},
	]
	return columns, rows


def _account_categories():
	s = frappe.get_cached_doc("Ataa Settings")
	donation_accounts = {s.restricted_income_account, s.unrestricted_income_account}
	membership = frappe.db.get_single_value("Membership Settings", "membership_income_account")
	expense_accounts = set(frappe.get_all("Account", filters={"root_type": "Expense"}, pluck="name"))

	def category_of(account):
		if account in donation_accounts:
			return "donations"
		if account == membership:
			return "memberships"
		if account == s.fund_transfers_in_account:
			return "transfers_in"
		if account == s.fund_transfers_out_account:
			return "transfers_out"
		if account in expense_accounts:
			return "expenses"
		return "other"

	return category_of


def _sums(f, start, end, exclusive_end=False):
	"""{(project, account): Σ(credit − debit)} on P&L accounts in the date range."""
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	query = (
		frappe.qb.from_(gle)
		.join(account)
		.on(account.name == gle.account)
		.select(gle.project, gle.account, Sum(gle.credit - gle.debit))
		.where((gle.is_cancelled == 0) & gle.project.isnotnull())
		.where(account.root_type.isin(["Income", "Expense"]))
		.groupby(gle.project, gle.account)
	)
	if start:
		query = query.where(gle.posting_date >= start)
	query = query.where(gle.posting_date < end if exclusive_end else gle.posting_date <= end)
	if f.project:
		query = query.where(gle.project == f.project)
	return {(p, a): flt(v) for p, a, v in query.run()}
