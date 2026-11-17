"""Moyasar (test environment) integration for the public donation page.

Flow (PRD 6.1):
1. Browser asks `create_pending_donation` -> server stores a Pending donation.
2. Browser shows Moyasar's card form with the *publishable* key, the amount in
   halalas and the donation id in `metadata`.
3. Moyasar redirects to /donate/callback?id=<payment_id>, and separately POSTs a
   webhook to `moyasar_webhook`.
4. Both paths call `verify_and_record_payment`, which fetches the payment from
   Moyasar with the *secret* key and trusts nothing coming from the browser.
   The donation row is locked, so callback + webhook together still mark it Paid once.
"""

import hmac
import json
import re

import frappe
import requests
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, flt, get_url, now_datetime

from ataa_hub.ataa_hub.doctype.moyasar_settings.moyasar_settings import get_moyasar_config
from ataa_hub.constants import (
	CHANNEL_WEBSITE,
	PROJECT_ACTIVE,
	STATUS_FAILED,
	STATUS_PAID,
	STATUS_PENDING,
)
from ataa_hub.services import get_or_create_donor

MOYASAR_API = "https://api.moyasar.com/v1"
MOYASAR_FORM_VERSION = "1.14.0"
PAYMENT_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
MOBILE_RE = re.compile(r"^\+9665\d{8}$")
MIN_AMOUNT, MAX_AMOUNT = 1, 100000


# ===================================================== step 1: pending donation


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=10 * 60)
def create_pending_donation(project_code=None, amount=None, donor_name=None, mobile=None):
	return create_pending_donation_for(project_code, amount, donor_name, mobile)


def create_pending_donation_for(project_code, amount, donor_name=None, mobile=None) -> dict:
	config = get_moyasar_config()
	if not config.publishable_key or not config.secret_key:
		frappe.throw(_("بوابة الدفع غير مهيأة بعد. أضيفي مفاتيح ميسّر التجريبية في إعدادات ميسّر."))

	project = frappe.db.get_value(
		"Donation Project",
		(project_code or "").strip().upper(),
		["name", "title", "status", "allow_custom_amount"],
		as_dict=True,
	)
	if not project or project.status != PROJECT_ACTIVE:
		frappe.throw(_("هذا المشروع لا يستقبل تبرعات حالياً."))

	amount = flt(amount, 2)
	options = [
		flt(row[0], 2)
		for row in frappe.db.get_values(
			"Donation Option", {"parent": project.name, "parenttype": "Donation Project"}, "amount"
		)
	]
	if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
		frappe.throw(_("المبلغ يجب أن يكون بين {0} و{1} ريال.").format(MIN_AMOUNT, MAX_AMOUNT))
	if not project.allow_custom_amount and amount not in options:
		frappe.throw(_("اختر أحد المبالغ الجاهزة لهذا المشروع."))

	mobile = (mobile or "").replace(" ", "") or None
	if mobile and not MOBILE_RE.match(mobile):
		frappe.throw(_("رقم الجوال يجب أن يكون بالصيغة +9665XXXXXXXX."))
	donor_name = (donor_name or "").strip()[:140] or None

	donation = frappe.get_doc(
		{
			"doctype": "Donation",
			"project": project.name,
			"amount": amount,
			"channel": CHANNEL_WEBSITE,
			"status": STATUS_PENDING,
			"donor": get_or_create_donor(donor_name, mobile),
			"donor_name": donor_name,
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
	"""Single source of truth for marking a website donation Paid.

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

	# Lock the row: if the callback and the webhook arrive together, the second one waits here.
	frappe.db.sql("select name from `tabDonation` where name = %s for update", (donation_id,))
	donation = frappe.get_doc("Donation", donation_id)

	if donation.channel != CHANNEL_WEBSITE:
		return frappe._dict(ok=False, reason="not_a_website_donation", donation=donation)

	if donation.status == STATUS_PAID:
		same = donation.payment_reference == payment_id
		return frappe._dict(
			ok=same, reason="already_paid" if same else "paid_by_other_payment", donation=donation
		)

	status = payment.get("status")
	if status == "paid":
		expected = int(round(flt(donation.amount) * 100))
		if cint(payment.get("amount")) != expected or (payment.get("currency") or "").upper() != "SAR":
			# Someone changed the amount in the browser: never mark it Paid.
			frappe.log_error(
				title="Moyasar: amount mismatch",
				message=f"Donation {donation.name} expects {expected} halalas, Moyasar says {payment.get('amount')}",
			)
			return frappe._dict(ok=False, reason="amount_mismatch", donation=donation)

		donation.status = STATUS_PAID
		donation.payment_reference = payment_id
		donation.paid_on = now_datetime()
		donation.raw_payload = json.dumps(_audit_fields(payment), ensure_ascii=False)
		donation.flags.ignore_permissions = True
		donation.save()
		return frappe._dict(ok=True, reason="recorded", donation=donation)

	if status == "failed" and donation.status == STATUS_PENDING:
		donation.status = STATUS_FAILED
		donation.payment_reference = payment_id
		donation.raw_payload = json.dumps(_audit_fields(payment), ensure_ascii=False)
		donation.flags.ignore_permissions = True
		donation.save()
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
	"""Paid Moyasar payments created between two dates (inclusive), newest first."""
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
		for p in batch:
			created = (p.get("created_at") or "")[:10]
			if start <= created <= end and p.get("status") == "paid":
				payments.append(p)

		oldest = min(((p.get("created_at") or "")[:10] for p in batch), default="")
		meta = body.get("meta") or {}
		if not batch or not meta.get("next_page") or (oldest and oldest < start):
			break
	return payments
