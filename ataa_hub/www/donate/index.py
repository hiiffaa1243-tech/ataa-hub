import frappe

from ataa_hub.projects import list_public_projects

no_cache = 1


def get_context(context):
	"""/donate — cards of every public project, balances read from the General Ledger."""
	context.no_cache = 1
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.projects = list_public_projects()
	return context
