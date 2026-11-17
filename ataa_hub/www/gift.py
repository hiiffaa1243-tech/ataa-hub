import frappe

from ataa_hub.public import gift_page

no_cache = 1


def get_context(context):
	"""/gift/<token> — the gift card page shared with the recipient. No donor data."""
	context.no_cache = 1
	context.gift = gift_page(frappe.form_dict.get("token"))
	if not context.gift:
		raise frappe.DoesNotExistError
	return context
