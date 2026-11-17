"""Fundraising event live data (PRD §7.3).

The public booth screen cannot use socket.io on v16 (guests are rejected, M0
finding), so it polls `ataa_hub.public.event_feed` every 5 s. That endpoint is
cached per event and the cache is cleared the moment a donation of the event is
submitted or cancelled, so polling stays cheap and the screen is still instant.
Logged-in staff views also get a `publish_realtime` message.

The feed never contains donor data: amount, project, terminal and time only.
"""

import frappe
from frappe.query_builder.functions import Count, Sum
from frappe.utils import add_to_date, flt, format_time, get_datetime, now_datetime

CACHE_KEY = "ataa_event_feed:"
CACHE_SECONDS = 30
LATEST_ROWS = 12
REALTIME_EVENT = "ataa_event_donation"


def get_event_feed(event_code: str | None) -> dict | None:
	code = (event_code or "").strip().upper()
	if not code:
		return None
	cached = frappe.cache.get_value(CACHE_KEY + code)
	if cached is not None:
		return cached or None  # {} = "no such screen", cached too
	feed = build_event_feed(code) or {}
	frappe.cache.set_value(CACHE_KEY + code, feed, expires_in_sec=CACHE_SECONDS)
	return feed or None


def clear_event_feed(event_code: str | None) -> None:
	if event_code:
		frappe.cache.delete_value(CACHE_KEY + event_code.upper())


def build_event_feed(code: str, now=None) -> dict | None:
	event = frappe.db.get_value(
		"Fundraising Event",
		code,
		[
			"event_code",
			"event_name",
			"location",
			"status",
			"start_datetime",
			"end_datetime",
			"target_amount",
			"live_screen_enabled",
		],
		as_dict=True,
	)
	if not event or not event.live_screen_enabled:
		return None

	now = get_datetime(now or now_datetime())
	d = frappe.qb.DocType("Donation")
	base = frappe.qb.from_(d).where((d.fundraising_event == code) & (d.docstatus == 1))

	total, count = base.select(Sum(d.amount), Count(d.name)).run()[0]
	last_hour = base.select(Sum(d.amount)).where(d.paid_at >= add_to_date(now, hours=-1)).run()[0][0]

	labels = {
		r.terminal_id: r.label or r.terminal_id
		for r in frappe.get_all(
			"Fundraising Event Terminal",
			filters={"parenttype": "Fundraising Event", "parent": code},
			fields=["terminal_id", "label"],
		)
	}
	by_project = [
		{"project_title": title, "amount": flt(amount), "count": n}
		for title, amount, n in base.select(d.project_title, Sum(d.amount), Count(d.name))
		.groupby(d.project, d.project_title)
		.orderby(Sum(d.amount), order=frappe.qb.desc)
		.run()
	]
	by_terminal = [
		{"terminal": labels.get(tid, tid or "—"), "amount": flt(amount), "count": n}
		for tid, amount, n in base.select(d.terminal_id, Sum(d.amount), Count(d.name))
		.groupby(d.terminal_id)
		.orderby(Sum(d.amount), order=frappe.qb.desc)
		.run()
	]
	latest = [
		{
			"amount": flt(amount),
			"project_title": title,
			"terminal": labels.get(tid, tid or "—"),
			"card_scheme": scheme,
			"time": format_time(paid_at, "HH:mm") if paid_at else None,
		}
		for amount, title, tid, scheme, paid_at in base.select(
			d.amount, d.project_title, d.terminal_id, d.card_scheme, d.paid_at
		)
		.orderby(d.paid_at, order=frappe.qb.desc)
		.orderby(d.creation, order=frappe.qb.desc)
		.limit(LATEST_ROWS)
		.run()
	]

	target = flt(event.target_amount)
	total = flt(total)
	return {
		"event_code": event.event_code,
		"event_name": event.event_name,
		"location": event.location,
		"status": event.status,
		"open": event.status == "Active"
		and get_datetime(event.start_datetime) <= now <= get_datetime(event.end_datetime),
		"target": target,
		"total": total,
		"count": count or 0,
		"progress": round(min(total / target * 100, 100), 1) if target else None,
		"last_hour": flt(last_hour),
		"by_project": by_project,
		"by_terminal": by_terminal,
		"latest": latest,
		"updated_at": now.strftime("%H:%M:%S"),
	}


def on_donation_change(doc, method=None):
	"""Donation submit / cancel: refresh the booth screen and tell staff views."""
	if not doc.get("fundraising_event"):
		return
	clear_event_feed(doc.fundraising_event)
	frappe.publish_realtime(
		REALTIME_EVENT,
		{
			"event_code": doc.fundraising_event,
			"amount": flt(doc.amount),
			"project_title": doc.project_title,
			"cancelled": doc.docstatus == 2,
		},
		after_commit=True,
	)
