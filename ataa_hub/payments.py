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
from ataa_hub.constants import CHANNEL_BANK_TRANSFER, CHANNEL_WEBSITE
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


# ============================================================ cart checkout
# One checkout = one Draft Donation per cart line. A card payment covers all of them
# (Moyasar metadata `donation_ids`); a bank transfer creates them with the receipt attached.

MAX_CART_LINES = 20
MAX_QTY = 100
GIFT_OCCASIONS = ("Other", "Eid", "Ramadan", "Wedding", "Newborn", "Graduation", "In Memory")
PROOF_TYPES = {
	".pdf": b"%PDF",
	".png": b"\x89PNG",
	".jpg": b"\xff\xd8",
	".jpeg": b"\xff\xd8",
	".webp": b"RIFF",
}
MAX_PROOF_BYTES = 5 * 1024 * 1024


def _donor_fields(donor_name, mobile, email) -> dict:
	mobile = normalize_mobile(mobile)
	if mobile and not is_valid_mobile(mobile):
		frappe.throw(_("رقم الجوال يجب أن يكون بالصيغة +9665XXXXXXXX."))
	email = (email or "").strip() or None
	if email and not frappe.utils.validate_email_address(email):
		frappe.throw(_("البريد الإلكتروني غير صحيح."))
	donor_name = (donor_name or "").strip()[:140] or None
	return {
		"donor": get_or_create_donor(donor_name, mobile, email),
		"donor_name": donor_name,
		"donor_mobile": mobile,
		"donor_email": email,
	}


def _gift_fields(gift) -> dict:
	if not gift:
		return {}
	gift = frappe._dict(gift)
	mobile = normalize_mobile(gift.recipient_mobile)
	if mobile and not is_valid_mobile(mobile):
		frappe.throw(_("رقم جوال المُهدى إليه غير صحيح."))
	return {
		"is_gift": 1,
		"recipient_name": (gift.recipient_name or "").strip()[:140],
		"recipient_mobile": mobile,
		"recipient_email": (gift.recipient_email or "").strip() or None,
		"occasion": gift.occasion if gift.occasion in GIFT_OCCASIONS else "Other",
		"gift_message": (gift.message or "").strip()[:500] or None,
		"show_amount_on_gift": cint(gift.show_amount),
		"sender": (gift.sender_name or "").strip()[:140] or None,
	}


def cart_lines(items) -> list[frappe._dict]:
	"""Check every line against the live project (amounts are never taken on trust)."""
	if isinstance(items, str):
		items = frappe.parse_json(items)
	if not items or not isinstance(items, list):
		frappe.throw(_("السلة فارغة."))
	if len(items) > MAX_CART_LINES:
		frappe.throw(_("الحد الأقصى {0} مشروعاً في السلة.").format(MAX_CART_LINES))

	lines = []
	for raw in items:
		item = frappe._dict(raw or {})
		project = get_public_project(item.project_code)
		if not project:
			frappe.throw(_("أحد المشاريع في السلة لا يستقبل تبرعات حالياً."))
		unit, qty = flt(item.amount, 2), cint(item.qty) if item.qty is not None else 1
		if qty < 1 or qty > MAX_QTY:
			frappe.throw(_("الكمية يجب أن تكون بين 1 و{0}.").format(MAX_QTY))
		if not project.allow_custom_amount and unit not in [o.amount for o in project.options]:
			frappe.throw(_("اختر أحد المبالغ الجاهزة لمشروع {0}.").format(project.title))
		amount = flt(unit * qty, 2)
		if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
			frappe.throw(_("مبلغ كل مشروع يجب أن يكون بين {0} و{1} ريال.").format(MIN_AMOUNT, MAX_AMOUNT))
		lines.append(frappe._dict(project=project, amount=amount, gift=_gift_fields(item.gift)))
	return lines


def _insert_drafts(lines, channel, donor: dict, extra=None) -> list:
	donations = []
	for line in lines:
		gift = dict(line.gift)
		sender = gift.pop("sender", None)
		values = {
			"doctype": "Donation",
			"project": line.project.name,
			"amount": line.amount,
			"channel": channel,
			"payment_status": "Awaiting Payment",
			**donor,
			**gift,
			**(extra or {}),
		}
		if sender and not values.get("donor_name"):
			values["donor_name"] = sender
		doc = frappe.get_doc(values)
		doc.flags.from_integration = True
		doc.insert(ignore_permissions=True)
		donations.append(doc)
	return donations


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=10 * 60)
def create_pending_cart(items=None, donor_name=None, mobile=None, email=None):
	return create_pending_cart_for(items, donor_name, mobile, email)


def create_pending_cart_for(items, donor_name=None, mobile=None, email=None) -> dict:
	config = get_moyasar_config()
	if not config.publishable_key or not config.secret_key:
		frappe.throw(_("بوابة الدفع غير مهيأة بعد. أضيفي مفاتيح ميسّر التجريبية في إعدادات ميسّر."))
	lines = cart_lines(items)
	donations = _insert_drafts(lines, CHANNEL_WEBSITE, _donor_fields(donor_name, mobile, email))
	total = flt(sum(d.amount for d in donations), 2)
	ids = [d.name for d in donations]
	return {
		"donation_ids": ids,
		"amount": total,
		"amount_halalas": int(round(total * 100)),
		"currency": "SAR",
		"description": f"تبرع لـ {len(ids)} مشروع ({', '.join(ids)})"[:250],
		"publishable_key": config.publishable_key,
		"callback_url": get_url("/donate/callback"),
		"metadata": {"donation_ids": ",".join(ids)},
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=10 * 60)
def submit_bank_transfer(
	items=None, bank_account=None, file_name=None, file_data=None, donor_name=None, mobile=None, email=None
):
	return submit_bank_transfer_for(items, bank_account, file_name, file_data, donor_name, mobile, email)


def submit_bank_transfer_for(
	items, bank_account, file_name, file_data, donor_name=None, mobile=None, email=None
) -> dict:
	"""Bank transfer from the checkout: Draft donations with the receipt; the accountant
	submits them after checking the bank statement (same rule as M2)."""
	lines = cart_lines(items)
	account = frappe.db.get_value(
		"Bank Account", {"name": bank_account, "is_company_account": 1, "disabled": 0}, "name"
	)
	if not account:
		frappe.throw(_("اختر الحساب البنكي الذي حوّلت إليه."))
	content = _proof_bytes(file_name, file_data)

	donations = _insert_drafts(
		lines,
		CHANNEL_BANK_TRANSFER,
		_donor_fields(donor_name, mobile, email),
		{"raw_payload": json.dumps({"bank_account": account}, ensure_ascii=False)},
	)
	proof = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"transfer-{donations[0].name}{_ext(file_name)}",
			"content": content,
			"is_private": 1,
			"attached_to_doctype": "Donation",
			"attached_to_name": donations[0].name,
		}
	).insert(ignore_permissions=True)
	for d in donations:
		d.db_set("transfer_proof", proof.file_url)
	return {"donation_ids": [d.name for d in donations], "amount": flt(sum(d.amount for d in donations), 2)}


def _ext(file_name) -> str:
	name = (file_name or "").lower()
	return next((e for e in PROOF_TYPES if name.endswith(e)), "")


def _proof_bytes(file_name, file_data) -> bytes:
	import base64

	ext = _ext(file_name)
	if not ext or not file_data:
		frappe.throw(_("أرفق إيصال التحويل (PDF أو صورة)."))
	if "," in file_data[:100]:
		file_data = file_data.split(",", 1)[1]  # data:...;base64,
	try:
		content = base64.b64decode(file_data, validate=True)
	except Exception:
		frappe.throw(_("تعذرت قراءة ملف الإيصال."))
	if len(content) > MAX_PROOF_BYTES:
		frappe.throw(_("حجم الإيصال يجب ألا يتجاوز 5 ميجابايت."))
	if not content.startswith(PROOF_TYPES[ext]):
		frappe.throw(_("نوع ملف الإيصال غير مدعوم."))
	return content


def company_bank_accounts() -> list[dict]:
	"""The association's own bank accounts (ERPNext Bank Account, company accounts only)."""
	return frappe.get_all(
		"Bank Account",
		filters={"is_company_account": 1, "disabled": 0},
		fields=["name", "bank", "account_name", "iban", "bank_account_no"],
		order_by="is_default desc, bank asc",
		ignore_permissions=True,
	)


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

	metadata = payment.get("metadata") or {}
	ids = [x.strip() for x in str(metadata.get("donation_ids") or "").split(",") if x.strip()]
	if not ids and metadata.get("donation_id"):
		ids = [metadata["donation_id"]]
	if not ids or len(ids) > MAX_CART_LINES or not all(frappe.db.exists("Donation", i) for i in ids):
		frappe.log_error(
			title="Moyasar: payment without a known donation", message=json.dumps(payment, default=str)
		)
		return frappe._dict(ok=False, reason="unknown_donation")

	# Lock the rows (same order every time): if the callback and the webhook arrive
	# together, the second waits here.
	for name in sorted(ids):
		frappe.db.sql("select name from `tabDonation` where name = %s for update", (name,))
	donations = [frappe.get_doc("Donation", i) for i in ids]

	def result(ok, reason):
		return frappe._dict(ok=ok, reason=reason, donation=donations[0], donations=donations)

	if any(d.channel != CHANNEL_WEBSITE for d in donations):
		return result(False, "not_a_website_donation")

	if all(d.docstatus == 1 for d in donations):
		same = all(d.payment_reference == payment_id for d in donations)
		return result(same, "already_paid" if same else "paid_by_other_payment")
	if any(d.docstatus != 0 for d in donations):
		return result(False, "cancelled")

	status = payment.get("status")
	if status == "paid":
		expected = sum(int(round(flt(d.amount) * 100)) for d in donations)
		if cint(payment.get("amount")) != expected or (payment.get("currency") or "").upper() != "SAR":
			# Someone changed the amount in the browser: never record it.
			frappe.log_error(
				title="Moyasar: amount mismatch",
				message=f"Donations {', '.join(ids)} expect {expected} halalas, Moyasar says {payment.get('amount')}",
			)
			return result(False, "amount_mismatch")

		audit = json.dumps(_audit_fields(payment), ensure_ascii=False)
		for n, d in enumerate(donations, start=1):
			d.payment_reference = payment_id
			d.idempotency_key = (
				f"moyasar:{payment_id}" if len(donations) == 1 else f"moyasar:{payment_id}:{n}"
			)
			d.raw_payload = audit
			d.flags.ignore_permissions = True
			d.submit()
		return result(True, "recorded")

	if status == "failed":
		audit = json.dumps(_audit_fields(payment), ensure_ascii=False)
		for d in donations:
			d.db_set({"payment_status": "Failed", "payment_reference": payment_id, "raw_payload": audit})
		return result(False, "failed")

	return result(False, status or "unknown_status")


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
