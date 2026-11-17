import frappe
from frappe.utils import fmt_money

from ataa_hub.payments import verify_and_record_payment

no_cache = 1


def get_context(context):
	"""/donate/callback?id=<payment_id> — Moyasar sends the donor here after paying.

	The query string (id, status, message) is NOT trusted: the server fetches the
	payment from Moyasar with the secret key and checks status, amount and donation id.
	"""
	context.no_cache = 1
	context.csrf_token = frappe.sessions.get_csrf_token()

	try:
		result = verify_and_record_payment(frappe.form_dict.get("id"))
		# Website pages are GET requests, which Frappe rolls back by default.
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="Moyasar callback failed")
		result = frappe._dict(ok=False, reason="verification_unavailable")

	context.success = bool(result.ok)
	context.reason = result.reason
	donation = result.get("donation")
	if donation:
		context.receipt = donation.name
		context.project_title = donation.project_title
		context.project_code = frappe.db.get_value("Project", donation.project, "project_code")
		context.amount_label = fmt_money(donation.amount, currency="SAR")
	return context
