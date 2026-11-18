import frappe
from frappe.utils import flt, fmt_money

from ataa_hub.ataa_hub.doctype.donation.donation import gift_url
from ataa_hub.payments import verify_and_record_payment

no_cache = 1


def get_context(context):
	"""/donate/callback?id=<payment_id> — Moyasar sends the donor here after paying.

	The query string (id, status, message) is NOT trusted: the server fetches the
	payment from Moyasar with the secret key and checks status, amount and donation ids.
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
	donations = result.get("donations") or ([result.donation] if result.get("donation") else [])
	context.receipts = [
		frappe._dict(
			name=d.name,
			project_title=d.project_title,
			gift_url=gift_url(d.gift_token) if d.is_gift and d.docstatus == 1 else None,
		)
		for d in donations
	]
	context.amount_label = fmt_money(sum(flt(d.amount) for d in donations), currency="SAR")
	return context
