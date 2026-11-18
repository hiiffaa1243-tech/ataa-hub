import frappe
from frappe.utils import fmt_money

from ataa_hub.memberships import complete_signup, tier_row

no_cache = 1


def get_context(context):
	"""/membership/callback?id=<payment_id> — nothing in the query string is trusted:
	the payment and its saved-card token are fetched from Moyasar with the secret key."""
	context.no_cache = 1
	context.csrf_token = frappe.sessions.get_csrf_token()
	try:
		result = complete_signup(frappe.form_dict.get("id"))
		frappe.db.commit()  # GET requests are rolled back by default
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="Membership callback failed")
		result = frappe._dict(ok=False, reason="verification_unavailable")

	context.success = bool(result.ok)
	context.reason = result.reason
	if result.ok:
		tier = result.get("tier") or frappe.db.get_value("Customer", result.customer, "membership_tier")
		row = tier_row(tier) if tier else None
		context.tier_label = (row.label_ar if row else None) or tier
		context.amount_label = fmt_money(row.annual_amount, currency="SAR") if row else ""
	return context
