"""Moyasar Reconciliation (PRD §10): Moyasar's paid payments vs our Donations and
membership Payment Entries. The logic lives in ataa_hub.reconciliation (also run daily)."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from ataa_hub.reconciliation import reconcile


def execute(filters=None):
	f = frappe._dict(filters or {})
	to_date = getdate(f.to_date or nowdate())
	from_date = getdate(f.from_date or add_days(to_date, -7))
	rows = reconcile(from_date, to_date)
	if f.only_issues:
		rows = [r for r in rows if r["status"] != "Matched"]

	columns = [
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 150},
		{"fieldname": "payment_id", "label": _("Moyasar Payment"), "fieldtype": "Data", "width": 290},
		{"fieldname": "created_at", "label": _("Moyasar Date"), "fieldtype": "Data", "width": 110},
		{"fieldname": "moyasar_amount", "label": _("Moyasar Amount"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "doctype", "label": _("Document Type"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "document",
			"label": _("Document"),
			"fieldtype": "Dynamic Link",
			"options": "doctype",
			"width": 170,
		},
		{"fieldname": "our_amount", "label": _("Our Amount"), "fieldtype": "Currency", "width": 120},
	]
	return columns, rows
