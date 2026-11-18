"""Number Cards for the three workspaces (PRD §10). Type "Custom": each card calls
one of these methods. Money comes from the General Ledger, counts from documents.
"""

import frappe
from frappe.query_builder.functions import Coalesce, Sum
from frappe.utils import flt, get_first_day, nowdate

from ataa_hub.accounting import get_available, get_donation_income_accounts
from ataa_hub.constants import (
	FUND_RESTRICTED,
	FUND_UNRESTRICTED,
	ROLE_ACCOUNTANT,
	ROLE_EXECUTIVE,
	ROLE_PROJECT_MANAGER,
	STATE_APPROVED,
	STATE_PENDING_ACCOUNTANT,
	STATE_PENDING_EXECUTIVE,
)

LEADERSHIP = (ROLE_EXECUTIVE, ROLE_ACCOUNTANT, "System Manager")


def _card(value, fieldtype="Int", route=None, route_options=None):
	out = {"value": value, "fieldtype": fieldtype}
	if route:
		out["route"] = route
	if route_options:
		out["route_options"] = route_options
	return out


def _gl_sum(accounts=None, fund_type=None, since=None) -> float:
	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	project = frappe.qb.DocType("Project")
	q = (
		frappe.qb.from_(gle)
		.join(account)
		.on(account.name == gle.account)
		.select(Coalesce(Sum(gle.credit - gle.debit), 0))
		.where((gle.is_cancelled == 0) & account.root_type.isin(["Income", "Expense"]))
	)
	if accounts is not None:
		q = q.where(gle.account.isin(accounts or [""]))
	if since:
		q = q.where(gle.posting_date >= since)
	if fund_type:
		q = q.join(project).on(project.name == gle.project).where(project.fund_type == fund_type)
	return flt(q.run()[0][0])


# ------------------------------------------------------------ Executive Director


@frappe.whitelist()
def donations_this_month(filters=None):
	frappe.only_for(LEADERSHIP)
	value = _gl_sum(get_donation_income_accounts(), since=get_first_day(nowdate()))
	return _card(value, "Currency", ["query-report", "Donations by Project and Channel"])


@frappe.whitelist()
def active_members(filters=None):
	frappe.only_for(LEADERSHIP)
	value = frappe.db.count("Customer", {"membership_status": "Active"})
	return _card(value, route=["List", "Customer"], route_options={"membership_status": "Active"})


@frappe.whitelist()
def membership_revenue(filters=None):
	"""Annual recurring revenue from paying members (memberships are billed yearly)."""
	frappe.only_for(LEADERSHIP)
	amounts = {
		r.tier: flt(r.annual_amount)
		for r in frappe.get_all(
			"Membership Tier",
			filters={"parenttype": "Membership Settings"},
			fields=["tier", "annual_amount"],
		)
	}
	billed = frappe.get_all(
		"Customer",
		filters={"membership_status": ("in", ("Active", "Payment Pending"))},
		pluck="membership_tier",
	)
	return _card(sum(amounts.get(t, 0) for t in billed), "Currency", ["query-report", "Membership Report"])


@frappe.whitelist()
def approvals_waiting(filters=None):
	frappe.only_for(LEADERSHIP)
	value = frappe.db.count(
		"Disbursement Request", {"workflow_state": STATE_PENDING_EXECUTIVE}
	) + frappe.db.count("Fund Allocation", {"workflow_state": STATE_PENDING_EXECUTIVE})
	return _card(
		value,
		route=["List", "Disbursement Request"],
		route_options={"workflow_state": STATE_PENDING_EXECUTIVE},
	)


@frappe.whitelist()
def restricted_balance(filters=None):
	frappe.only_for(LEADERSHIP)
	return _card(
		_gl_sum(fund_type=FUND_RESTRICTED), "Currency", ["query-report", "Monthly Project Statement"]
	)


@frappe.whitelist()
def unrestricted_balance(filters=None):
	frappe.only_for(LEADERSHIP)
	return _card(
		_gl_sum(fund_type=FUND_UNRESTRICTED), "Currency", ["query-report", "Monthly Project Statement"]
	)


# ------------------------------------------------------------ Project Manager


def _my_projects():
	from ataa_hub.permissions import assigned_projects, is_restricted_project_manager

	if is_restricted_project_manager():
		return sorted(assigned_projects(frappe.session.user))
	return frappe.get_all("Project", filters={"status": "Open", "fund_type": FUND_RESTRICTED}, pluck="name")


@frappe.whitelist()
def my_projects_available(filters=None):
	frappe.only_for((ROLE_PROJECT_MANAGER, *LEADERSHIP))
	value = sum(get_available(p, lock=False) for p in _my_projects())
	return _card(value, "Currency", ["List", "Project"])


@frappe.whitelist()
def my_open_requests(filters=None):
	frappe.only_for((ROLE_PROJECT_MANAGER, *LEADERSHIP))
	value = frappe.db.count(
		"Disbursement Request",
		{"project": ("in", _my_projects() or [""]), "workflow_state": ("not in", ("Paid", "Rejected"))},
	)
	return _card(value, route=["List", "Disbursement Request"])


# ------------------------------------------------------------ Accountant


@frappe.whitelist()
def bank_transfers_to_verify(filters=None):
	frappe.only_for(LEADERSHIP)
	value = frappe.db.count("Donation", {"channel": "Bank Transfer", "docstatus": 0})
	return _card(
		value, route=["List", "Donation"], route_options={"channel": "Bank Transfer", "docstatus": 0}
	)


@frappe.whitelist()
def requests_to_review(filters=None):
	frappe.only_for(LEADERSHIP)
	value = frappe.db.count("Disbursement Request", {"workflow_state": STATE_PENDING_ACCOUNTANT})
	return _card(
		value,
		route=["List", "Disbursement Request"],
		route_options={"workflow_state": STATE_PENDING_ACCOUNTANT},
	)


@frappe.whitelist()
def requests_to_pay(filters=None):
	frappe.only_for(LEADERSHIP)
	value = frappe.db.count("Disbursement Request", {"workflow_state": STATE_APPROVED, "docstatus": 1})
	return _card(
		value, route=["List", "Disbursement Request"], route_options={"workflow_state": STATE_APPROVED}
	)


@frappe.whitelist()
def charges_needing_attention(filters=None):
	frappe.only_for(LEADERSHIP)
	value = frappe.db.count("Membership Charge Attempt", {"status": "Needs Review"}) + frappe.db.count(
		"Customer", {"membership_status": "Suspended"}
	)
	return _card(value, route=["List", "Membership Charge Attempt"], route_options={"status": "Needs Review"})


@frappe.whitelist()
def reconciliation_issues(filters=None):
	frappe.only_for(LEADERSHIP)
	value = frappe.db.get_single_value("Moyasar Settings", "reconciliation_issues") or 0
	return _card(value, route=["query-report", "Moyasar Reconciliation"], route_options={"only_issues": 1})


CARDS = {
	# name: (label, method, colour)
	"Ataa Donations This Month": ("تبرعات هذا الشهر", "donations_this_month", "#AD8F52"),
	"Ataa Active Members": ("الأعضاء النشطون", "active_members", "#1F6F5C"),
	"Ataa Membership Revenue": ("إيراد العضويات السنوي", "membership_revenue", "#1F6F5C"),
	"Ataa Approvals Waiting": ("موافقات بانتظارك", "approvals_waiting", "#B45309"),
	"Ataa Restricted Balance": ("رصيد المشاريع المقيدة", "restricted_balance", "#AD8F52"),
	"Ataa Unrestricted Balance": ("رصيد الصندوق العام", "unrestricted_balance", "#4B5563"),
	"Ataa My Projects Available": ("المتاح في مشاريعي", "my_projects_available", "#AD8F52"),
	"Ataa My Open Requests": ("طلبات صرفي المفتوحة", "my_open_requests", "#B45309"),
	"Ataa Bank Transfers To Verify": ("تحويلات بنكية للتحقق", "bank_transfers_to_verify", "#B45309"),
	"Ataa Requests To Review": ("طلبات صرف للمراجعة", "requests_to_review", "#B45309"),
	"Ataa Requests To Pay": ("طلبات معتمدة للصرف", "requests_to_pay", "#1F6F5C"),
	"Ataa Charges Needing Attention": ("عضويات تحتاج متابعة", "charges_needing_attention", "#B91C1C"),
	"Ataa Reconciliation Issues": ("فروقات مطابقة ميسّر", "reconciliation_issues", "#B91C1C"),
}
