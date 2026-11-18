"""Membership Report (PRD §10): members per tier and status, ARR, new, cancelled and churn.

Statuses are the derived Customer.membership_status (M5); ARR (annual recurring revenue)
counts members who are still billed (Active + Payment Pending) at the tier's annual amount.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, getdate, nowdate

from ataa_hub.constants import PAID_TIERS, TIER_HONORARY

STATUSES = ("Active", "Payment Pending", "Suspended", "Cancelled")


def execute(filters=None):
	f = frappe._dict(filters or {})
	from_date = getdate(f.from_date or get_first_day(nowdate()))
	to_date = getdate(f.to_date or nowdate())
	amounts = {
		r.tier: flt(r.annual_amount)
		for r in frappe.get_all(
			"Membership Tier",
			filters={"parenttype": "Membership Settings"},
			fields=["tier", "annual_amount"],
		)
	}

	members = frappe.get_all(
		"Customer",
		filters={"membership_tier": ("is", "set")},
		fields=["name", "membership_tier", "membership_status", "member_since", "membership_subscription"],
	)
	cancelled_in_period = set(
		frappe.get_all(
			"Subscription",
			filters={"cancelation_date": ("between", (from_date, to_date))},
			pluck="name",
		)
	)

	rows = []
	for tier in (*PAID_TIERS, TIER_HONORARY):
		group = [m for m in members if m.membership_tier == tier]
		row = {"tier": tier, "annual_amount": amounts.get(tier, 0)}
		for status in STATUSES:
			row[frappe.scrub(status)] = sum(1 for m in group if m.membership_status == status)
		row["new"] = sum(
			1 for m in group if m.member_since and from_date <= getdate(m.member_since) <= to_date
		)
		row["cancelled_in_period"] = sum(1 for m in group if m.membership_subscription in cancelled_in_period)
		billed = row["active"] + row["payment_pending"]
		row["arr"] = billed * row["annual_amount"] if tier != TIER_HONORARY else 0
		base = billed + row["suspended"] + row["cancelled_in_period"]
		row["churn"] = round(row["cancelled_in_period"] / base * 100, 1) if base else 0
		rows.append(row)

	columns = [
		{"fieldname": "tier", "label": _("Tier"), "fieldtype": "Data", "width": 110},
		{"fieldname": "annual_amount", "label": _("Annual (SAR)"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "active", "label": _("Active"), "fieldtype": "Int", "width": 80},
		{"fieldname": "payment_pending", "label": _("Payment Pending"), "fieldtype": "Int", "width": 120},
		{"fieldname": "suspended", "label": _("Suspended"), "fieldtype": "Int", "width": 100},
		{"fieldname": "cancelled", "label": _("Cancelled"), "fieldtype": "Int", "width": 100},
		{"fieldname": "new", "label": _("New in Period"), "fieldtype": "Int", "width": 110},
		{
			"fieldname": "cancelled_in_period",
			"label": _("Cancelled in Period"),
			"fieldtype": "Int",
			"width": 140,
		},
		{"fieldname": "arr", "label": _("ARR (SAR)"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "churn", "label": _("Churn %"), "fieldtype": "Percent", "width": 90},
	]
	summary = [
		{
			"label": _("ARR"),
			"value": sum(r["arr"] for r in rows),
			"datatype": "Currency",
			"indicator": "Green",
		},
		{"label": _("Active members"), "value": sum(r["active"] for r in rows), "datatype": "Int"},
		{
			"label": _("Suspended"),
			"value": sum(r["suspended"] for r in rows),
			"datatype": "Int",
			"indicator": "Red",
		},
	]
	return columns, rows, None, None, summary
