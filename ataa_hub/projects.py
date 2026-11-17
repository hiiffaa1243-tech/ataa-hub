"""Public view of donation projects: one place used by the donation page, and from M3 the API."""

import frappe
from frappe.utils import flt

from ataa_hub.accounting import get_project_balance

PUBLIC_FILTERS = {"status": "Open", "is_active": "Yes", "is_public": 1, "fund_type": ("is", "set")}
FIELDS = [
	"name",
	"project_code",
	"project_name",
	"public_title",
	"public_description",
	"public_image",
	"fund_type",
	"target_amount",
	"allow_custom_amount",
	"impact_unit_label",
	"impact_units_per_sar",
]


def _decorate(row) -> frappe._dict:
	"""Add balances from the GL and Arabic-ready labels (numbers pre-formatted for Jinja)."""
	balance = get_project_balance(row.name)
	progress = flt(balance.progress_percent)
	row.code = row.project_code
	row.title = row.public_title or row.project_name
	row.description = row.public_description
	row.image = row.public_image
	row.collected_amount = balance.donation_income
	row.progress_percent = balance.progress_percent
	row.progress_display = round(min(progress, 100), 1)
	row.progress_label = f"{progress:.0f}%" if balance.progress_percent is not None else ""
	row.collected_label = f"{balance.donation_income:,.0f}"
	row.target_label = f"{flt(row.target_amount):,.0f}" if row.target_amount else ""
	row.options = [
		frappe._dict(label=o.label, amount=flt(o.amount, 2), amount_label=f"{flt(o.amount):,.0f}")
		for o in frappe.get_all(
			"Project Donation Option",
			filters={"parent": row.name, "parenttype": "Project"},
			fields=["label", "amount"],
			order_by="idx asc",
		)
	]
	return row


def list_public_projects(names: list[str] | None = None) -> list[frappe._dict]:
	filters = dict(PUBLIC_FILTERS)
	if names is not None:
		filters["name"] = ("in", names or [""])
	rows = frappe.get_all("Project", filters=filters, fields=FIELDS, order_by="creation asc")
	return [_decorate(r) for r in rows]


def get_public_project(project_code: str | None) -> frappe._dict | None:
	code = (project_code or "").strip().upper()
	if not code:
		return None
	row = frappe.get_all("Project", filters={**PUBLIC_FILTERS, "project_code": code}, fields=FIELDS, limit=1)
	return _decorate(row[0]) if row else None
