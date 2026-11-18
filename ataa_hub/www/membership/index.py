import frappe
from frappe.utils import flt

from ataa_hub import memberships
from ataa_hub.ataa_hub.doctype.moyasar_settings.moyasar_settings import get_moyasar_config
from ataa_hub.payments import MOYASAR_FORM_VERSION

no_cache = 1


def get_context(context):
	"""/membership — the six annual tiers with their benefits; sign up pays the first year."""
	context.no_cache = 1
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.tiers = [
		frappe._dict(
			tier=row.tier,
			label=row.label_ar or row.tier,
			price=f"{flt(row.annual_amount):,.0f}",
			colour=row.colour or "#A7ABB1",
			finish=row.finish or "Silver",
			benefits=[b.strip() for b in (row.benefits or "").splitlines() if b.strip()],
		)
		for row in sorted(memberships.settings().tiers, key=lambda r: flt(r.annual_amount))
		if row.subscription_plan
	]
	context.tiers_json = {t.tier: {"label": t.label, "price": t.price} for t in context.tiers}
	customer = memberships.customer_for_user()
	context.logged_in = bool(customer)
	context.current = (
		frappe.db.get_value("Customer", customer, ["membership_tier", "membership_status"], as_dict=True)
		if customer
		else None
	)
	if context.current:
		row = memberships.tier_row(context.current.membership_tier)
		context.current.label = row.label_ar if row else None
	context.can_join = not (
		context.current
		and context.current.membership_status
		and context.current.membership_status != "Cancelled"
	)
	context.payments_ready = bool(get_moyasar_config().publishable_key)
	context.moyasar_version = MOYASAR_FORM_VERSION
	return context
