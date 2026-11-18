import frappe

from ataa_hub.ataa_hub.doctype.moyasar_settings.moyasar_settings import get_moyasar_config
from ataa_hub.payments import MOYASAR_FORM_VERSION, company_bank_accounts

no_cache = 1


def get_context(context):
	"""/donate/checkout — pay the whole cart by card (Moyasar) or by bank transfer with a receipt."""
	context.no_cache = 1
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.payments_ready = bool(get_moyasar_config().publishable_key)
	context.moyasar_version = MOYASAR_FORM_VERSION
	context.bank_accounts = company_bank_accounts()
	context.donor = _signed_in_donor()
	return context


def _signed_in_donor() -> frappe._dict:
	"""Prefill name and mobile for a signed-in donor (never trusted: the server re-reads them)."""
	if frappe.session.user == "Guest":
		return frappe._dict()
	from ataa_hub.memberships import customer_for_user

	customer = customer_for_user()
	if not customer:
		return frappe._dict()
	row = frappe.db.get_value("Customer", customer, ["customer_name", "mobile_no"], as_dict=True) or {}
	mobile = (row.get("mobile_no") or "").replace("+966", "0", 1)
	return frappe._dict(name=row.get("customer_name"), mobile=mobile)
