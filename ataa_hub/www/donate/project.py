import frappe
from frappe.utils import flt

from ataa_hub.ataa_hub.doctype.moyasar_settings.moyasar_settings import get_moyasar_config
from ataa_hub.constants import PROJECT_ACTIVE
from ataa_hub.payments import MOYASAR_FORM_VERSION
from ataa_hub.www.donate.index import decorate

no_cache = 1


def get_context(context):
	"""/donate/project?code=SUQYA-01 — choose an amount, then pay with Moyasar's form."""
	context.no_cache = 1
	code = (frappe.form_dict.get("code") or "").strip().upper()
	project = frappe.db.get_value(
		"Donation Project",
		code,
		[
			"name",
			"title",
			"description",
			"image",
			"status",
			"target_amount",
			"collected_amount",
			"progress_percent",
			"allow_custom_amount",
		],
		as_dict=True,
	)
	if not project or project.status != PROJECT_ACTIVE:
		raise frappe.DoesNotExistError

	context.project = decorate(project)
	options = frappe.db.get_values(
		"Donation Option",
		{"parent": project.name, "parenttype": "Donation Project"},
		["label", "amount"],
		as_dict=True,
		order_by="idx asc",
	)
	for o in options:
		o.amount = flt(o.amount, 2)
		o.amount_label = f"{o.amount:,.0f}"
	context.options = options
	context.payments_ready = bool(get_moyasar_config().publishable_key)
	context.moyasar_version = MOYASAR_FORM_VERSION
	context.csrf_token = frappe.sessions.get_csrf_token()
	return context
