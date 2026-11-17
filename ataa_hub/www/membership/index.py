import frappe
from frappe.utils import fmt_money

from ataa_hub import memberships
from ataa_hub.ataa_hub.doctype.moyasar_settings.moyasar_settings import get_moyasar_config
from ataa_hub.payments import MOYASAR_FORM_VERSION

no_cache = 1


def get_context(context):
	"""/membership — choose a monthly tier, then pay the first month with a saved card."""
	context.no_cache = 1
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.tiers = [
		frappe._dict(
			tier=row.tier,
			label=row.label_ar or row.tier,
			amount_label=fmt_money(row.monthly_amount, currency="SAR"),
			colour=row.colour or "#AD8F52",
		)
		for row in memberships.settings().tiers
		if row.subscription_plan
	]
	customer = memberships.customer_for_user()
	context.logged_in = bool(customer)
	context.current = (
		frappe.db.get_value("Customer", customer, ["membership_tier", "membership_status"], as_dict=True)
		if customer
		else None
	)
	context.payments_ready = bool(get_moyasar_config().publishable_key)
	context.moyasar_version = MOYASAR_FORM_VERSION
	return context
