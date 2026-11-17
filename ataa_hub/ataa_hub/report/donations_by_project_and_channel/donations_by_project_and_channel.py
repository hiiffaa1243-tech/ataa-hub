"""Donations by Project and Channel (PRD §10): submitted donations grouped by project and channel."""

import frappe
from frappe import _
from frappe.query_builder.functions import Count, Sum
from frappe.utils import flt


def execute(filters=None):
	f = frappe._dict(filters or {})
	d = frappe.qb.DocType("Donation")
	query = (
		frappe.qb.from_(d)
		.select(d.project, d.project_title, d.channel, Count(d.name), Sum(d.amount))
		.where(d.docstatus == 1)
		.groupby(d.project, d.project_title, d.channel)
		.orderby(d.project_title)
		.orderby(Sum(d.amount), order=frappe.qb.desc)
	)
	if f.from_date:
		query = query.where(d.posting_date >= f.from_date)
	if f.to_date:
		query = query.where(d.posting_date <= f.to_date)
	if f.project:
		query = query.where(d.project == f.project)
	if f.channel:
		query = query.where(d.channel == f.channel)

	rows = [
		{"project": p, "project_title": t, "channel": c, "count": n, "amount": flt(a)}
		for p, t, c, n, a in query.run()
	]
	columns = [
		{
			"fieldname": "project",
			"label": _("Project"),
			"fieldtype": "Link",
			"options": "Project",
			"width": 130,
		},
		{"fieldname": "project_title", "label": _("Project Title"), "fieldtype": "Data", "width": 220},
		{"fieldname": "channel", "label": _("Channel"), "fieldtype": "Data", "width": 130},
		{"fieldname": "count", "label": _("Donations"), "fieldtype": "Int", "width": 100},
		{"fieldname": "amount", "label": _("Amount (SAR)"), "fieldtype": "Currency", "width": 140},
	]
	by_channel = {}
	for row in rows:
		by_channel[row["channel"]] = by_channel.get(row["channel"], 0) + row["amount"]
	chart = {
		"data": {
			"labels": list(by_channel),
			"datasets": [{"name": _("Amount"), "values": list(by_channel.values())}],
		},
		"type": "bar",
	}
	total = sum(r["amount"] for r in rows)
	summary = [{"label": _("Total"), "value": total, "datatype": "Currency", "indicator": "Green"}]
	return columns, rows, None, chart, summary
