"""Donations grouped by project and channel for a date range (Excel export is built in)."""

import frappe
from frappe import _
from frappe.utils import add_months, flt, today

from ataa_hub.constants import STATUS_PAID


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = filters.from_date or add_months(today(), -12)
	to_date = filters.to_date or today()

	conditions = [["status", "=", STATUS_PAID], ["paid_on", "between", [from_date, to_date]]]
	if filters.project:
		conditions.append(["project", "=", filters.project])
	if filters.channel:
		conditions.append(["channel", "=", filters.channel])

	# get_list (not get_all) applies row permissions: a Project Manager sees only their projects.
	rows = frappe.get_list(
		"Donation",
		filters=conditions,
		fields=[
			"project",
			"project_title",
			"channel",
			"count(name) as donations_count",
			"sum(amount) as total_amount",
		],
		group_by="project, project_title, channel",
		order_by="project asc",
		limit_page_length=0,
	)
	rows.sort(key=lambda r: (r.project, -flt(r.total_amount)))
	for row in rows:
		row.channel_label = _(row.channel)

	return get_columns(), rows, None, get_chart(rows), get_summary(rows)


def get_columns():
	return [
		{
			"fieldname": "project",
			"label": _("رمز المشروع"),
			"fieldtype": "Link",
			"options": "Donation Project",
			"width": 130,
		},
		{"fieldname": "project_title", "label": _("المشروع"), "fieldtype": "Data", "width": 220},
		{"fieldname": "channel_label", "label": _("القناة"), "fieldtype": "Data", "width": 140},
		{"fieldname": "donations_count", "label": _("عدد التبرعات"), "fieldtype": "Int", "width": 120},
		{"fieldname": "total_amount", "label": _("المبلغ"), "fieldtype": "Currency", "width": 150},
	]


def get_chart(rows):
	by_channel = {}
	for row in rows:
		by_channel[row.channel_label] = by_channel.get(row.channel_label, 0) + flt(row.total_amount)
	if not by_channel:
		return None
	return {
		"data": {
			"labels": list(by_channel),
			"datasets": [{"name": _("المبلغ"), "values": list(by_channel.values())}],
		},
		"type": "bar",
		"colors": ["#0F766E"],
		"fieldtype": "Currency",
	}


def get_summary(rows):
	total = sum(flt(r.total_amount) for r in rows)
	count = sum(int(r.donations_count or 0) for r in rows)
	return [
		{"label": _("إجمالي التبرعات"), "value": total, "datatype": "Currency", "indicator": "Green"},
		{"label": _("عدد التبرعات"), "value": count, "datatype": "Int", "indicator": "Blue"},
		{"label": _("متوسط التبرع"), "value": total / count if count else 0, "datatype": "Currency"},
	]
