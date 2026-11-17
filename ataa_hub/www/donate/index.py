import frappe
from frappe.utils import flt

from ataa_hub.constants import PROJECT_ACTIVE

no_cache = 1


def get_context(context):
	"""/donate — cards of every active project with its progress bar."""
	context.no_cache = 1
	context.csrf_token = frappe.sessions.get_csrf_token()
	projects = frappe.get_all(
		"Donation Project",
		filters={"status": PROJECT_ACTIVE},
		fields=[
			"name",
			"title",
			"description",
			"image",
			"target_amount",
			"collected_amount",
			"progress_percent",
		],
		order_by="progress_percent desc",
	)
	for p in projects:
		decorate(p)
	context.projects = projects
	return context


def decorate(project):
	"""Pre-formatted numbers for the template (Arabic UI, SAR)."""
	project.progress_display = round(min(flt(project.progress_percent), 100), 1)
	project.progress_label = f"{flt(project.progress_percent):.0f}%"
	project.collected_label = f"{flt(project.collected_amount):,.0f}"
	project.target_label = f"{flt(project.target_amount):,.0f}"
	return project
