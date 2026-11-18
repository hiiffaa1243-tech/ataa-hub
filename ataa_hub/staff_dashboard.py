"""Data and actions for the staff home page (desk page `ataa-home`).

One call returns everything the signed-in person's dashboard shows. Every list goes
through frappe.get_list, so a project manager only ever sees their own projects;
actions go through the normal workflow / custody functions and their checks.
"""

import re

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, cint, flt, get_first_day, nowdate

from ataa_hub import dashboards
from ataa_hub.accounting import get_project_balance
from ataa_hub.constants import (
	PROJECT_EDITOR_ROLES,
	ROLE_ACCOUNTANT,
	ROLE_EXECUTIVE,
	ROLE_PROJECT_MANAGER,
	STATE_APPROVED,
	STATE_PENDING_ACCOUNTANT,
	STATE_PENDING_EXECUTIVE,
)
from ataa_hub.permissions import is_restricted_project_manager

WORKFLOW_DOCTYPES = ("Disbursement Request", "Fund Allocation")
OPEN_CUSTODY = ("Open", "Closing Requested")


def _view() -> str:
	roles = set(frappe.get_roles())
	if roles & {ROLE_EXECUTIVE, "System Manager"}:
		return "executive"
	if ROLE_ACCOUNTANT in roles:
		return "accountant"
	if ROLE_PROJECT_MANAGER in roles:
		return "pm"
	frappe.throw(_("لوحة التحكم لموظفي الجمعية فقط."), frappe.PermissionError)


@frappe.whitelist()
def get_dashboard() -> dict:
	view = _view()
	out = {
		"view": view,
		"full_name": frappe.utils.get_fullname(frappe.session.user),
		"projects": _projects(),
		"custody": _custody(view),
	}
	out.update({"executive": _executive, "accountant": _accountant, "pm": _pm}[view]())
	return out


# ------------------------------------------------------------------ shared blocks


def _projects() -> list[dict]:
	rows = frappe.get_list(
		"Project",
		filters={"fund_type": ("is", "set"), "status": ("!=", "Cancelled")},
		fields=[
			"name",
			"project_name",
			"public_title",
			"project_code",
			"fund_type",
			"status",
			"is_public",
			"public_image",
		],
		order_by="creation desc",
		limit_page_length=60,
	)
	since = add_days(nowdate(), -30)
	recent = {
		r.project: r
		for r in frappe.get_list(
			"Donation",
			filters={
				"docstatus": 1,
				"posting_date": (">=", since),
				"project": ("in", [p.name for p in rows] or [""]),
			},
			fields=["project", {"COUNT": "name", "as": "n"}, {"SUM": "amount", "as": "amount"}],
			group_by="project",
		)
	}
	out = []
	for p in rows:
		b = get_project_balance(p.name)
		r = recent.get(p.name)
		out.append(
			{
				**p,
				"title": p.public_title or p.project_name,
				"target": b.target_amount,
				"collected": b.donation_income,
				"balance": b.balance,
				"committed": b.committed,
				"available": b.available,
				"progress": b.progress_percent,
				"last30": flt(r.amount) if r else 0,
				"last30_count": cint(r.n) if r else 0,
			}
		)
	return out


def _donations(limit=8, filters=None) -> list[dict]:
	return frappe.get_list(
		"Donation",
		filters={"docstatus": 1, **(filters or {})},
		fields=["name", "donor_name", "project_title", "amount", "channel", "posting_date", "is_gift"],
		order_by="creation desc",
		limit_page_length=limit,
	)


def _requests(filters, limit=20) -> list[dict]:
	return frappe.get_list(
		"Disbursement Request",
		filters=filters,
		fields=[
			"name",
			"project",
			"project_title",
			"purpose",
			"amount",
			"workflow_state",
			"requested_by",
			"creation",
			"available_balance_at_request",
		],
		order_by="creation desc",
		limit_page_length=limit,
	)


def _allocations(filters, limit=20) -> list[dict]:
	return frappe.get_list(
		"Fund Allocation",
		filters=filters,
		fields=[
			"name",
			"from_project",
			"to_project",
			"to_project_title",
			"reason",
			"amount",
			"workflow_state",
			"requested_by",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=limit,
	)


def _custody(view) -> list[dict]:
	if view == "pm":
		filters = {"status": ("!=", "Rejected"), "modified": (">=", add_days(nowdate(), -120))}
	else:
		# Everything still open, plus what was closed lately (with its report)
		filters = None
		or_filters = {
			"status": ("in", ("Requested", *OPEN_CUSTODY)),
			"closed_on": (">=", add_days(nowdate(), -60)),
		}
	return frappe.get_list(
		"Custody",
		filters=filters,
		or_filters=None if view == "pm" else or_filters,
		fields=[
			"name",
			"project",
			"project_title",
			"purpose",
			"amount",
			"spent",
			"remaining",
			"status",
			"holder",
			"holder_name",
			"creation",
			"report_file",
		],
		order_by="modified desc",
		limit_page_length=40,
	)


def _kpi(fn) -> float:
	try:
		return fn()["value"]
	except frappe.PermissionError:
		return None


# ------------------------------------------------------------------ per role


def _executive() -> dict:
	return {
		"kpis": {
			"donations_month": _kpi(dashboards.donations_this_month),
			"active_members": _kpi(dashboards.active_members),
			"membership_revenue": _kpi(dashboards.membership_revenue),
			"restricted": _kpi(dashboards.restricted_balance),
			"unrestricted": _kpi(dashboards.unrestricted_balance),
			"open_custody": sum(
				flt(c.amount)
				for c in frappe.get_all(
					"Custody", filters={"status": ("in", OPEN_CUSTODY)}, fields=["amount"]
				)
			),
		},
		"approvals": _requests({"workflow_state": STATE_PENDING_EXECUTIVE}),
		"allocation_approvals": _allocations({"workflow_state": STATE_PENDING_EXECUTIVE}),
		"recent_requests": _requests({"workflow_state": ("not in", (STATE_PENDING_EXECUTIVE,))}, limit=8),
		"donations": _donations(),
	}


def _accountant() -> dict:
	return {
		"kpis": {
			"donations_month": _kpi(dashboards.donations_this_month),
			"bank_transfers": frappe.db.count("Donation", {"channel": "Bank Transfer", "docstatus": 0}),
			"to_review": frappe.db.count(
				"Disbursement Request", {"workflow_state": STATE_PENDING_ACCOUNTANT}
			),
			"to_pay": frappe.db.count(
				"Disbursement Request", {"workflow_state": STATE_APPROVED, "docstatus": 1}
			),
			"charges": _kpi(dashboards.charges_needing_attention),
			"reconciliation": _kpi(dashboards.reconciliation_issues),
		},
		"to_review": _requests({"workflow_state": STATE_PENDING_ACCOUNTANT}),
		"to_pay": _requests({"workflow_state": STATE_APPROVED, "docstatus": 1}),
		"bank_transfers": frappe.get_list(
			"Donation",
			filters={"channel": "Bank Transfer", "docstatus": 0},
			fields=[
				"name",
				"donor_name",
				"project_title",
				"amount",
				"posting_date",
				"transfer_proof",
				"payment_reference",
			],
			order_by="creation desc",
			limit_page_length=20,
		),
		"donations": _donations(),
	}


def _pm() -> dict:
	mine = {"owner": frappe.session.user} if is_restricted_project_manager() else {}
	month = get_first_day(nowdate())
	return {
		"kpis": {"month_start": str(month)},
		"requests": _requests(
			{**mine, "workflow_state": ("!=", "Paid"), "modified": (">=", add_days(nowdate(), -120))}
		),
		"allocations": _allocations({**mine, "modified": (">=", add_days(nowdate(), -120))}, limit=10),
		"donations": _donations(10),
	}


# ------------------------------------------------------------------ actions


@frappe.whitelist()
def apply_action(doctype: str, name: str, action: str, reason: str | None = None) -> str:
	"""Approve / return / reject / mark paid from the dashboard (the workflow checks the role)."""
	if doctype not in WORKFLOW_DOCTYPES:
		frappe.throw(_("نوع مستند غير مدعوم."))
	doc = frappe.get_doc(doctype, name)
	reason = (reason or "").strip()
	if reason and action == "Reject":
		doc.rejection_reason = reason
	elif reason and action == "Return" and doctype == "Disbursement Request":
		doc.accountant_notes = reason
	doc = apply_workflow(doc, action)
	return doc.workflow_state


def _options(raw) -> list[dict]:
	rows = frappe.parse_json(raw) if isinstance(raw, str) else (raw or [])
	out = []
	for r in rows[:8]:
		label = (r.get("label") or "").strip()
		amount = flt(r.get("amount"))
		if label and amount > 0:
			out.append({"label": label[:60], "amount": amount})
	return out


@frappe.whitelist(methods=["POST"])
def create_project(data) -> str:
	"""The "إضافة مشروع" dialog. The creator is added to the project's team, so a
	project manager keeps seeing the project they just made."""
	if not set(frappe.get_roles()) & PROJECT_EDITOR_ROLES:
		frappe.throw(_("إضافة المشاريع لمدير المشاريع."), frappe.PermissionError)
	frappe.has_permission("Project", "create", throw=True)
	d = frappe._dict(frappe.parse_json(data) if isinstance(data, str) else data)
	code = re.sub(r"[^A-Z0-9-]", "", (d.project_code or "").strip().upper())
	if not (d.project_name or "").strip() or not code:
		frappe.throw(_("اسم المشروع ورمزه مطلوبان."))
	if frappe.db.exists("Project", {"project_code": code}):
		frappe.throw(_("الرمز {0} مستخدم لمشروع آخر.").format(code))
	if d.fund_type not in ("Restricted", "Unrestricted"):
		frappe.throw(_("اختر نوع الصندوق."))
	settings = frappe.get_cached_doc("Ataa Settings")
	project = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": d.project_name.strip(),
			"company": settings.company,
			"status": "Open",
			"project_code": code,
			"fund_type": d.fund_type,
			"target_amount": flt(d.target_amount),
			"is_public": cint(d.is_public),
			"allow_custom_amount": cint(d.allow_custom_amount),
			"public_title": (d.public_title or d.project_name).strip(),
			"public_description": (d.public_description or "").strip(),
			"public_image": d.public_image or None,
			"impact_unit_label": (d.impact_unit_label or "").strip() or None,
			"impact_units_per_sar": flt(d.impact_units_per_sar) or None,
			"expected_start_date": d.expected_start_date or None,
			"expected_end_date": d.expected_end_date or None,
			"donation_options": _options(d.options),
			"users": [{"user": frappe.session.user, "welcome_email_sent": 1}],
		}
	)
	# Create permission was checked above; without this flag Frappe drops the team row
	# a project manager may not write, and they would lose sight of their own project.
	project.insert(ignore_permissions=True)
	return project.name


@frappe.whitelist(methods=["POST"])
def create_disbursement_request(
	project: str, amount, purpose: str, supplier: str | None = None, attachment: str | None = None
) -> str:
	"""The "طلب صرف" dialog: create the request and send it to the accountant in one step."""
	frappe.has_permission("Disbursement Request", "create", throw=True)
	doc = frappe.get_doc(
		{
			"doctype": "Disbursement Request",
			"project": project,
			"amount": flt(amount),
			"purpose": (purpose or "").strip(),
			"supplier": supplier or None,
			"attachment": attachment or None,
			"requested_by": frappe.session.user,
		}
	).insert()
	apply_workflow(doc, "Submit for Review")
	return doc.name


@frappe.whitelist(methods=["POST"])
def create_custody(project: str, amount, purpose: str) -> str:
	"""The "طلب عهدة" dialog."""
	frappe.has_permission("Custody", "create", throw=True)
	doc = frappe.get_doc(
		{"doctype": "Custody", "project": project, "amount": flt(amount), "purpose": (purpose or "").strip()}
	)
	doc.insert()
	return doc.name
