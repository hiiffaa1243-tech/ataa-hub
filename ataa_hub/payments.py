"""Moyasar (test mode) for the public donation page (PRD §7.1).

1. Browser calls `create_pending_donation` → a **Draft** Donation (Awaiting Payment).
2. Browser shows Moyasar's form with the *publishable* key, the amount in
   halalas and the donation id in `metadata`.
3. Moyasar redirects to /donate/callback?id=<payment_id> and also POSTs a webhook.
4. Both paths call `verify_and_record_payment`, which fetches the payment with the
   *secret* key and trusts nothing from the browser. If it is paid with the right
   amount, the Donation is **submitted** (→ Journal Entry). The row is locked and
   the idempotency key `moyasar:<payment_id>` is unique, so callback + webhook
   arriving together still record it once.
"""

import hmac
import json
import re

import frappe
import requests
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, flt, get_url

from ataa_hub.ataa_hub.doctype.moyasar_settings.moyasar_settings import get_moyasar_config
from ataa_hub.constants import CHANNEL_WEBSITE
from ataa_hub.donors import get_or_create_donor, is_valid_mobile, normalize_mobile
from ataa_hub.projects import get_public_project

MOYASAR_API = "https://api.moyasar.com/v1"
MOYASAR_FORM_VERSION = "1.14.0"
PAYMENT_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
MIN_AMOUNT, MAX_AMOUNT = 1, 100000


# ===================================================== step 1: draft donation


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=10 * 60)
def create_pending_donation(project_code=None, amount=None, donor_name=None, mobile=None, email=None):
	return create_pending_donation_for(project_code, amount, donor_name, mobile, email)


def create_pending_donation_for(project_code, amount, donor_name=None, mobile=None, email=None) -> dict:
	config = get_moyasar_config()
	if not config.publishable_key or not config.secret_key:
		frappe.throw(_("بوابة الدفع غير مهيأة بعد. أضيفي مفاتيح ميسّر التجريبية في إعدادات ميسّر."))

	project = get_public_project(project_code)
	if not project:
		frappe.throw(_("هذا المشروع لا يستقبل تبرعات حالياً."))

	amount = flt(amount, 2)
	if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
		frappe.throw(_("المبلغ يجب أن يكون بين {0} و{1} ريال.").format(MIN_AMOUNT, MAX_AMOUNT))
	if not project.allow_custom_amount and amount not in [o.amount for o in project.options]:
		frappe.throw(_("اختر أحد المبالغ الجاهزة لهذا المشروع."))

	mobile = normalize_mobile(mobile)
	if mobile and not is_valid_mobile(mobile):
		frappe.throw(_("رقم الجوال يجب أن يكون بالصيغة +9665XXXXXXXX."))
	email = (email or "").strip() or None
	if email and not frappe.utils.validate_email_address(email):
		frappe.throw(_("البريد الإلكتروني غير صحيح."))
	donor_name = (donor_name or "").strip()[:140] or None

	donation = frappe.get_doc(
		{
			"doctype": "Donation",
			"project": project.name,
			"amount": amount,
			"channel": CHANNEL_WEBSITE,
			"payment_status": "Awaiting Payment",
			"donor": get_or_create_donor(donor_name, mobile, email),
			"donor_name": donor_name,
			"donor_mobile": mobile,
			"donor_email": email,
		}
	)
	donation.flags.from_integration = True
	donation.insert(ignore_permissions=True)

	return {
		"donation_id": donation.name,
		"amount": amount,
		"amount_halalas": int(round(amount * 100)),
		"currency": "SAR",
		"description": f"تبرع لمشروع {project.title} ({donation.name})",
		"publishable_key": config.publishable_key,
		"callback_url": get_url("/donate/callback"),
	}


# ============================================= step 4: verify with the secret key


def fetch_payment(payment_id: str) -> dict:
	config = get_moyasar_config()
	response = requests.get(f"{MOYASAR_API}/payments/{payment_id}", auth=(config.secret_key, ""), timeout=15)
	response.raise_for_status()
	return response.json()


def verify_and_record_payment(payment_id: str | None, payment: dict | None = None) -> frappe._dict:
	"""Single place that turns a Moyasar payment into a submitted Donation.

	`payment` can be injected by tests; in production it is always fetched from Moyasar.
	"""
	if not payment_id or not PAYMENT_ID_RE.match(payment_id):
		return frappe._dict(ok=False, reason="invalid_payment_id")

	if payment is None:
		payment = fetch_payment(payment_id)

	donation_id = (payment.get("metadata") or {}).get("donation_id")
	if not donation_id or not frappe.db.exists("Donation", donation_id):
		frappe.log_error(
			title="Moyasar: payment without a known donation", message=json.dumps(payment, default=str)
		)
		return frappe._dict(ok=False, reason="unknown_donation")

	# Lock the row: if the callback and the webhook arrive together, the second waits here.
	frappe.db.sql("select name from `tabDonation` where name = %s for update", (donation_id,))
	donation = frappe.get_doc("Donation", donation_id)

	if donation.channel != CHANNEL_WEBSITE:
		return frappe._dict(ok=False, reason="not_a_website_donation", donation=donation)

	if donation.docstatus == 1:
		same = donation.payment_reference == payment_id
		return frappe._dict(
			ok=same, reason="already_paid" if same else "paid_by_other_payment", donation=donation
		)
	if donation.docstatus == 2:
		return frappe._dict(ok=False, reason="cancelled", donation=donation)

	status = payment.get("status")
	if status == "paid":
		expected = int(round(flt(donation.amount) * 100))
		if cint(payment.get("amount")) != expected or (payment.get("currency") or "").upper() != "SAR":
			# Someone changed the amount in the browser: never record it.
			frappe.log_error(
				title="Moyasar: amount mismatch",
				message=f"Donation {donation.name} expects {expected} halalas, Moyasar says {payment.get('amount')}",
			)
			return frappe._dict(ok=False, reason="amount_mismatch", donation=donation)

		donation.payment_reference = payment_id
		donation.idempotency_key = f"moyasar:{payment_id}"
		donation.raw_payload = json.dumps(_audit_fields(payment), ensure_ascii=False)
		donation.flags.ignore_permissions = True
		donation.submit()
		return frappe._dict(ok=True, reason="recorded", donation=donation)

	if status == "failed":
		donation.db_set({"payment_status": "Failed", "payment_reference": payment_id})
		donation.db_set("raw_payload", json.dumps(_audit_fields(payment), ensure_ascii=False))
		return frappe._dict(ok=False, reason="failed", donation=donation)

	return frappe._dict(ok=False, reason=status or "unknown_status", donation=donation)


def _audit_fields(payment: dict) -> dict:
	source = payment.get("source") or {}
	return {
		"id": payment.get("id"),
		"status": payment.get("status"),
		"amount": payment.get("amount"),
		"currency": payment.get("currency"),
		"created_at": payment.get("created_at"),
		"metadata": payment.get("metadata"),
		"source": {
			"type": source.get("type"),
			"company": source.get("company"),
			"number": source.get("number"),
		},
	}


# ========================================================= backup path: webhook


@frappe.whitelist(allow_guest=True, methods=["POST"])
def moyasar_webhook():
	"""Moyasar calls this even if the donor closed the browser before the redirect."""
	config = get_moyasar_config()
	request = getattr(frappe.local, "request", None)
	event = (request.get_json(silent=True) if request is not None else None) or dict(frappe.local.form_dict)

	token = str(event.get("secret_token") or "")
	if not config.webhook_secret or not hmac.compare_digest(token, config.webhook_secret):
		frappe.local.response["http_status_code"] = 401
		return {"ok": False, "error": "invalid secret_token"}

	payment_id = (event.get("data") or {}).get("id")
	result = verify_and_record_payment(payment_id)
	return {"ok": True, "result": result.reason}


# ======================================================== reconciliation helper


def list_paid_payments(from_date, to_date, max_pages: int = 50) -> list[dict]:
	"""Paid Moyasar payments created between two dates (inclusive), newest first (used in M8)."""
	config = get_moyasar_config()
	if not config.secret_key:
		frappe.throw(_("أضيفي المفتاح السري لميسّر في إعدادات ميسّر لتشغيل تقرير المطابقة."))

	start, end = str(from_date), str(to_date)
	payments = []
	for page in range(1, max_pages + 1):
		response = requests.get(
			f"{MOYASAR_API}/payments", params={"page": page}, auth=(config.secret_key, ""), timeout=20
		)
		response.raise_for_status()
		body = response.json()
		batch = body.get("payments") or []
		payments += [
			p for p in batch if start <= (p.get("created_at") or "")[:10] <= end and p.get("status") == "paid"
		]
		oldest = min(((p.get("created_at") or "")[:10] for p in batch), default="")
		if not batch or not (body.get("meta") or {}).get("next_page") or (oldest and oldest < start):
			break
	return payments
