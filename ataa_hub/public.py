"""Data for public pages reached by an unguessable token (PRD §7.6, §8.2).

These pages show no donor personal data: no name, mobile or email of the donor.
"""

import re

import frappe
from frappe.utils import flt

TOKEN_RE = re.compile(r"^[0-9a-zA-Z]{20,64}$")


def _valid(token) -> bool:
	return bool(token) and bool(TOKEN_RE.match(str(token)))


def gift_page(token: str | None) -> frappe._dict | None:
	"""/gift/<token>: occasion, message, project and impact; the amount only if the donor opted in."""
	if not _valid(token):
		return None
	row = frappe.db.get_value(
		"Donation",
		{"gift_token": token, "is_gift": 1, "docstatus": 1},
		[
			"recipient_name",
			"occasion",
			"gift_message",
			"project",
			"project_title",
			"impact_units",
			"impact_unit_label",
			"show_amount_on_gift",
			"amount",
			"posting_date",
		],
		as_dict=True,
	)
	if not row:
		return None
	project = frappe.db.get_value(
		"Project", row.project, ["project_code", "public_image", "is_public"], as_dict=True
	)
	return frappe._dict(
		recipient_name=row.recipient_name,
		occasion=row.occasion if row.occasion and row.occasion != "Other" else None,
		gift_message=row.gift_message,
		project_title=row.project_title,
		project_code=project.project_code if project and project.is_public else None,
		image=project.public_image if project else None,
		impact_units=flt(row.impact_units),
		impact_unit_label=row.impact_unit_label,
		amount=flt(row.amount) if row.show_amount_on_gift else None,
		date=row.posting_date,
	)


def verify_page(token: str | None) -> frappe._dict | None:
	"""/verify/<token>: confirms a receipt number, date, amount and project."""
	if not _valid(token):
		return None
	row = frappe.db.get_value(
		"Donation",
		{"receipt_token": token, "docstatus": ("in", (1, 2))},
		["name", "posting_date", "amount", "project_title", "docstatus"],
		as_dict=True,
	)
	if not row:
		return None
	return frappe._dict(
		receipt=row.name,
		date=row.posting_date,
		amount=flt(row.amount),
		project_title=row.project_title,
		valid=row.docstatus == 1,
	)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def event_feed(event_code: str | None = None):
	"""Polled every 5 s by /event/<code>. Cached; no donor data (PRD §7.3)."""
	from ataa_hub.events import get_event_feed

	feed = get_event_feed(event_code)
	if not feed:
		frappe.local.response["http_status_code"] = 404
		return {"error": "not_found"}
	return feed
