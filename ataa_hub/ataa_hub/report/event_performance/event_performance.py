"""Event Performance (PRD §7.3): an event's donations per hour, per terminal or per card scheme."""

import frappe
from frappe import _
from frappe.query_builder.functions import Avg, Count, Sum
from frappe.utils import flt
from pypika.enums import DatePart
from pypika.functions import Extract

GROUPS = ("Hour", "Terminal", "Card Scheme")


def execute(filters=None):
	f = frappe._dict(filters or {})
	if not f.event:
		return [], []
	group = f.group_by if f.group_by in GROUPS else "Hour"
	d = frappe.qb.DocType("Donation")
	if group == "Hour":
		key = Extract(DatePart.hour, d.paid_at)
	elif group == "Terminal":
		key = d.terminal_id
	else:
		key = d.card_scheme

	query = (
		frappe.qb.from_(d)
		.select(key, Count(d.name), Sum(d.amount), Avg(d.amount))
		.where((d.fundraising_event == f.event) & (d.docstatus == 1))
		.groupby(key)
		.orderby(key)
	)
	rows = []
	for bucket, n, total, avg in query.run():
		label = f"{int(bucket):02d}:00" if group == "Hour" and bucket is not None else (bucket or "—")
		rows.append({"bucket": label, "count": n, "amount": flt(total), "average": flt(avg, 2)})

	columns = [
		{"fieldname": "bucket", "label": _(group), "fieldtype": "Data", "width": 160},
		{"fieldname": "count", "label": _("Donations"), "fieldtype": "Int", "width": 110},
		{"fieldname": "amount", "label": _("Amount (SAR)"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "average", "label": _("Average (SAR)"), "fieldtype": "Currency", "width": 130},
	]
	chart = {
		"data": {
			"labels": [r["bucket"] for r in rows],
			"datasets": [{"name": _("Amount"), "values": [r["amount"] for r in rows]}],
		},
		"type": "bar",
	}
	return columns, rows, None, chart
