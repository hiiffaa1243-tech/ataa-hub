import frappe

from ataa_hub.ataa_hub.doctype.moyasar_settings.moyasar_settings import get_moyasar_config
from ataa_hub.payments import MOYASAR_FORM_VERSION
from ataa_hub.projects import get_public_project

no_cache = 1


def get_context(context):
	"""/donate/project?code=SUQYA-01 — choose an amount, then pay with Moyasar's form."""
	context.no_cache = 1
	project = get_public_project(frappe.form_dict.get("code"))
	if not project:
		raise frappe.DoesNotExistError

	context.project = project
	context.options = project.options
	context.payments_ready = bool(get_moyasar_config().publishable_key)
	context.moyasar_version = MOYASAR_FORM_VERSION
	context.csrf_token = frappe.sessions.get_csrf_token()
	return context
