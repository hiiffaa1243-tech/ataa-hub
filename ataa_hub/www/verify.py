import frappe

from ataa_hub.public import verify_page

no_cache = 1


def get_context(context):
	"""/verify/<token> — opened from the QR on a receipt. Confirms it without donor data."""
	context.no_cache = 1
	context.receipt = verify_page(frappe.form_dict.get("token"))
	return context
