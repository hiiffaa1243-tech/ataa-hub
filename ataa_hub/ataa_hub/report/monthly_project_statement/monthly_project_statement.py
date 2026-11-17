"""Monthly statement per project — replaces the monthly Excel file per project (PRD 7).

For the chosen period: donations received, amounts disbursed, and the running totals.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, today

from ataa_hub.constants import STATE_DISBURSED, STATUS_PAID


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = filters.from_date or get_first_day(today())
	to_date = filters.to_date or get_last_day(today())

	project_filters = {}
	if filters.project:
		project_filters["name"] = filters.project

	projects = frappe.get_list(
		"Donation Project",
		filters=project_filters,
		fields=[
			"name",
			"title",
			"status",
			"target_amount",
			"collected_amount",
			"disbursed_amount",
			"available_balance",
			"progress_percent",
		],
		order_by="title asc",
		limit_page_length=0,
	)
	if not projects:
		return get_columns(), []

	names = [p.name for p in projects]
	donations = _totals(
		"Donation",
		[
			["project", "in", names],
			["status", "=", STATUS_PAID],
			["paid_on", "between", [from_date, to_date]],
		],
	)
	disbursed = _totals(
		"Disbursement Request",
		[
			["project", "in", names],
			["docstatus", "=", 1],
			["workflow_state", "=", STATE_DISBURSED],
			["disbursed_on", "between", [from_date, to_date]],
		],
	)

	data = []
	for p in projects:
		received, count = donations.get(p.name, (0, 0))
		spent, _count = disbursed.get(p.name, (0, 0))
		data.append(
			{
				"project": p.name,
				"title": p.title,
				"status": _(p.status),
				"period_donations": received,
				"period_donations_count": count,
				"period_disbursed": spent,
				"period_net": received - spent,
				"collected_amount": p.collected_amount,
				"disbursed_amount": p.disbursed_amount,
				"available_balance": p.available_balance,
				"progress_percent": p.progress_percent,
			}
		)

	summary = [
		{
			"label": _("تبرعات الفترة"),
			"value": sum(r["period_donations"] for r in data),
			"datatype": "Currency",
			"indicator": "Green",
		},
		{
			"label": _("مصروفات الفترة"),
			"value": sum(r["period_disbursed"] for r in data),
			"datatype": "Currency",
			"indicator": "Red",
		},
		{
			"label": _("إجمالي الأرصدة المتاحة"),
			"value": sum(flt(r["available_balance"]) for r in data),
			"datatype": "Currency",
			"indicator": "Blue",
		},
	]
	return get_columns(), data, None, None, summary


def _totals(doctype, filters):
	rows = frappe.get_list(
		doctype,
		filters=filters,
		fields=["project", "sum(amount) as total", "count(name) as cnt"],
		group_by="project",
		limit_page_length=0,
	)
	return {r.project: (flt(r.total), int(r.cnt or 0)) for r in rows}


def get_columns():
	return [
		{
			"fieldname": "project",
			"label": _("رمز المشروع"),
			"fieldtype": "Link",
			"options": "Donation Project",
			"width": 120,
		},
		{"fieldname": "title", "label": _("المشروع"), "fieldtype": "Data", "width": 200},
		{"fieldname": "status", "label": _("الحالة"), "fieldtype": "Data", "width": 90},
		{"fieldname": "period_donations", "label": _("تبرعات الفترة"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "period_donations_count", "label": _("عددها"), "fieldtype": "Int", "width": 70},
		{"fieldname": "period_disbursed", "label": _("مصروف الفترة"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "period_net", "label": _("صافي الفترة"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "collected_amount", "label": _("إجمالي المحصّل"), "fieldtype": "Currency", "width": 140},
		{
			"fieldname": "disbursed_amount",
			"label": _("إجمالي المصروف"),
			"fieldtype": "Currency",
			"width": 140,
		},
		{
			"fieldname": "available_balance",
			"label": _("الرصيد المتاح"),
			"fieldtype": "Currency",
			"width": 140,
		},
		{"fieldname": "progress_percent", "label": _("نسبة الإنجاز"), "fieldtype": "Percent", "width": 110},
	]
