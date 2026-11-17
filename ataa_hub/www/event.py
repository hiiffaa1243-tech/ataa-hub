import frappe

from ataa_hub.events import get_event_feed

no_cache = 1


def get_context(context):
	"""/event/<event_code> — full-screen live display for the booth (PRD §7.3)."""
	context.no_cache = 1
	context.feed = get_event_feed(frappe.form_dict.get("event_code"))
	if not context.feed:
		raise frappe.DoesNotExistError
	return context
