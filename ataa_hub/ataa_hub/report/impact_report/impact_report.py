"""Impact Report (PRD §7.10, §10): impact units per project per month, frozen on each donation."""

import frappe
from frappe import _
from frappe.query_builder.functions import Count, Sum
from frappe.utils import flt
from pypika.enums import DatePart
from pypika.functions import Extract


def execute(filters=None):
	f = frappe._dict(filters or {})
	d = frappe.qb.DocType("Donation")
	year, month = Extract(DatePart.year, d.posting_date), Extract(DatePart.month, d.posting_date)
	query = (
		frappe.qb.from_(d)
		.select(
			year,
			month,
			d.project_title,
			d.impact_unit_label,
			Count(d.name),
			Sum(d.amount),
			Sum(d.impact_units),
		)
		.where(d.docstatus == 1)
		.groupby(year, month, d.project, d.project_title, d.impact_unit_label)
		.orderby(year)
		.orderby(month)
		.orderby(d.project_title)
	)
	if f.from_date:
		query = query.where(d.posting_date >= f.from_date)
	if f.to_date:
		query = query.where(d.posting_date <= f.to_date)
	if f.project:
		query = query.where(d.project == f.project)

	rows = [
		{
			"period": f"{int(y)}-{int(m):02d}",
			"project_title": title,
			"impact_units": flt(units),
			"impact_unit_label": label or "",
			"count": n,
			"amount": flt(amount),
		}
		for y, m, title, label, n, amount, units in query.run()
	]
	columns = [
		{"fieldname": "period", "label": _("Month"), "fieldtype": "Data", "width": 100},
		{"fieldname": "project_title", "label": _("Project Title"), "fieldtype": "Data", "width": 220},
		{"fieldname": "impact_units", "label": _("Impact Units"), "fieldtype": "Float", "width": 120},
		{"fieldname": "impact_unit_label", "label": _("Unit"), "fieldtype": "Data", "width": 160},
		{"fieldname": "count", "label": _("Donations"), "fieldtype": "Int", "width": 100},
		{"fieldname": "amount", "label": _("Amount (SAR)"), "fieldtype": "Currency", "width": 130},
	]
	return columns, rows
