import frappe

from ataa_hub.projects import get_public_project, list_public_projects

no_cache = 1


def get_context(context):
	"""/donate/project?code=SUQYA-01 — the project, its donation options and the buy box."""
	context.no_cache = 1
	project = get_public_project(frappe.form_dict.get("code"))
	if not project:
		raise frappe.DoesNotExistError

	context.project = project
	context.others = [p for p in list_public_projects() if p.name != project.name][:3]
	context.csrf_token = frappe.sessions.get_csrf_token()
	return context
