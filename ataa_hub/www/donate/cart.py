import frappe

no_cache = 1


def get_context(context):
	"""/donate/cart — the cart lives in the browser; the server re-checks it at checkout."""
	context.no_cache = 1
	context.csrf_token = frappe.sessions.get_csrf_token()
	return context
