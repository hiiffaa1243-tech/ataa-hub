"""Memberships (PRD §7.5): native Subscription + Sales Invoice + Payment Entry,
charged through a saved Moyasar token.

    sign-up:  Moyasar form (save card) → complete_signup → Donor Payment Method
              → Subscription (ERPNext creates and submits the first invoice)
              → Payment Entry for the first payment
    monthly:  ERPNext's Subscription job creates the invoice → charge_due_invoices
              → Membership Charge Attempt (committed first) → Moyasar → Payment Entry
    dunning:  failure 1 → retry +3 days, failure 2 → retry +7 days,
              failure 3 → Suspended + Accountant notified
    safety:   an invoice with a Processing / Succeeded / Needs Review attempt is never
              charged again; the invoice row is locked while deciding.

Customer `membership_status` is always *derived* (refresh_membership_status) from the
Subscription, the open membership invoices and their attempts, never set by hand.
"""

import uuid
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, flt, get_url, getdate, now_datetime, nowdate

from ataa_hub import moyasar
from ataa_hub.ataa_hub.doctype.donor_payment_method.donor_payment_method import (
	STATUS_ACTIVE as CARD_ACTIVE,
)
from ataa_hub.ataa_hub.doctype.donor_payment_method.donor_payment_method import (
	get_default_method,
)
from ataa_hub.ataa_hub.doctype.membership_charge_attempt.membership_charge_attempt import (
	FAILED,
	NEEDS_REVIEW,
	PROCESSING,
	SUCCEEDED,
)
from ataa_hub.ataa_hub.doctype.moyasar_settings.moyasar_settings import get_moyasar_config
from ataa_hub.constants import (
	CUSTOMER_GROUP_DONORS,
	MEMBERSHIP_NUMBER_PREFIX,
	ROLE_ACCOUNTANT,
	ROLE_EXECUTIVE,
	TIER_HONORARY,
)
from ataa_hub.donors import get_or_create_donor, is_valid_mobile, normalize_mobile, update_lifetime_giving
from ataa_hub.spending import notify, users_with_role

ACTIVE = "Active"
PAYMENT_PENDING = "Payment Pending"
SUSPENDED = "Suspended"
CANCELLED = "Cancelled"

MAX_ATTEMPTS = 3
CHARGEABLE_TOKEN_STATUSES = ("active", "save_only")
SIGNUP_CACHE_KEY = "ataa_membership_signup:"
SIGNUP_TTL = 24 * 60 * 60
STALE_PROCESSING_MINUTES = 30
POLICY_CANCEL_PAID = "Cancel paid membership at period end"


# ================================================================= helpers


@contextmanager
def as_administrator():
	"""Callback pages and jobs act for the system (the donor is often a Guest)."""
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		yield
	finally:
		frappe.set_user(user)


def _commit():
	# Tests run inside one transaction that is rolled back at the end.
	if not frappe.in_test:
		frappe.db.commit()


def settings():
	return frappe.get_single("Membership Settings")


def tier_row(tier: str):
	return next((row for row in settings().tiers if row.tier == tier), None)


def tier_for_plan(plan: str | None) -> str | None:
	if not plan:
		return None
	return frappe.db.get_value(
		"Membership Tier", {"parenttype": "Membership Settings", "subscription_plan": plan}, "tier"
	)


def membership_items() -> set[str]:
	return {
		item
		for item in frappe.get_all(
			"Membership Tier", filters={"parenttype": "Membership Settings"}, pluck="item"
		)
		if item
	}


def halalas(amount) -> int:
	return int(round(flt(amount) * 100))


def customer_email(customer: str) -> str | None:
	contact = frappe.db.get_value("Customer", customer, "customer_primary_contact")
	if contact:
		return frappe.db.get_value("Contact", contact, "email_id")
	return None


def customer_for_user(user: str | None = None) -> str | None:
	"""The donor (Customer) linked to a portal user through their Contact."""
	user = user or frappe.session.user
	if user == "Guest":
		return None
	contact = frappe.db.get_value("Contact", {"user": user}, "name")
	if not contact:
		return None
	return frappe.db.get_value(
		"Dynamic Link",
		{"parenttype": "Contact", "parent": contact, "link_doctype": "Customer"},
		"link_name",
	)


def open_membership_invoices(customer: str) -> list[str]:
	return frappe.get_all(
		"Sales Invoice",
		filters={"customer": customer, "is_membership": 1, "docstatus": 1, "outstanding_amount": (">", 0)},
		order_by="due_date asc",
		pluck="name",
	)


def failed_attempts(invoice: str) -> int:
	return frappe.db.count("Membership Charge Attempt", {"sales_invoice": invoice, "status": FAILED})


# ================================================================ sign-up


def start_signup_for(tier, full_name=None, email=None, mobile=None) -> dict:
	"""Step 1: check the request and return what Moyasar's form needs (save card on)."""
	config = get_moyasar_config()
	if not config.publishable_key or not config.secret_key:
		frappe.throw(_("بوابة الدفع غير مهيأة بعد. أضيفي مفاتيح ميسّر التجريبية في إعدادات ميسّر."))

	row = tier_row(tier)
	if not row or not row.subscription_plan:
		frappe.throw(_("اختر مستوى عضوية صحيحاً."))

	customer = customer_for_user()
	if customer:
		email = email or customer_email(customer)
	else:
		mobile = normalize_mobile(mobile)
		email = (email or "").strip().lower() or None
		if not is_valid_mobile(mobile):
			frappe.throw(_("رقم الجوال يجب أن يكون بالصيغة +9665XXXXXXXX."))
		if not email or not frappe.utils.validate_email_address(email):
			frappe.throw(_("البريد الإلكتروني مطلوب للدخول إلى صفحة العضوية."))
		customer = _guest_customer(full_name, mobile, email)

	if has_live_membership(customer):
		frappe.throw(_("لديك عضوية قائمة. يمكنك تغيير المستوى من صفحة عضويتك."))

	intent = frappe.generate_hash(length=24)
	frappe.cache.set_value(
		SIGNUP_CACHE_KEY + intent,
		{"tier": tier, "customer": customer, "email": email, "amount": flt(row.annual_amount)},
		expires_in_sec=SIGNUP_TTL,
	)
	return {
		"intent": intent,
		"tier": tier,
		"amount": flt(row.annual_amount),
		"amount_halalas": halalas(row.annual_amount),
		"currency": "SAR",
		"description": f"عضوية عطاء — {row.label_ar or tier} (سنوية)",
		"publishable_key": config.publishable_key,
		"callback_url": get_url("/membership/callback"),
		"metadata": {"membership_signup": intent},
	}


def _guest_customer(full_name, mobile, email) -> str:
	"""Match by mobile, but never attach a membership (and later a portal login) to
	someone else's donor record: a known mobile must come with one of its emails."""
	existing = frappe.db.get_value("Customer", {"donor_mobile": mobile}, "name")
	if existing:
		known = customer_emails(existing)
		if known and email not in known:
			frappe.throw(_("رقم الجوال مسجّل ببريد آخر. سجّل الدخول بحسابك أولاً."))
	return get_or_create_donor(full_name, mobile, email)


def customer_emails(customer: str) -> set[str]:
	contact = frappe.db.get_value("Customer", customer, "customer_primary_contact")
	if not contact:
		return set()
	return {
		(e or "").lower()
		for e in frappe.get_all(
			"Contact Email", filters={"parenttype": "Contact", "parent": contact}, pluck="email_id"
		)
	}


def has_live_membership(customer: str) -> bool:
	subscription = frappe.db.get_value("Customer", customer, "membership_subscription")
	if not subscription:
		return False
	return frappe.db.get_value("Subscription", subscription, "status") not in ("Cancelled", "Completed")


def complete_signup(payment_id: str | None, payment: dict | None = None) -> frappe._dict:
	"""Step 2 (callback page): verify the payment with the secret key, then build the membership.

	Safe to call twice for the same payment (callback + refresh): the second call
	finds the Payment Entry and returns it.
	"""
	from ataa_hub.payments import PAYMENT_ID_RE

	if not payment_id or not PAYMENT_ID_RE.match(payment_id):
		return frappe._dict(ok=False, reason="invalid_payment_id")

	client = moyasar.get_client()
	payment = payment or client.fetch_payment(payment_id)
	intent_id = (payment.get("metadata") or {}).get("membership_signup")
	intent = frappe.cache.get_value(SIGNUP_CACHE_KEY + intent_id) if intent_id else None

	done = _signup_payment_entry(payment_id)
	if done:
		return frappe._dict(ok=True, reason="already_recorded", **done)
	if not intent:
		if payment.get("status") == "paid":
			frappe.log_error(
				title="Moyasar: paid membership sign-up without a known intent",
				message=f"payment {payment_id} — refund or create the membership by hand",
			)
		return frappe._dict(ok=False, reason="unknown_signup")

	intent = frappe._dict(intent)
	with as_administrator():
		# Lock the donor: callback and a double click arrive together → one membership.
		frappe.db.sql("select name from `tabCustomer` where name = %s for update", (intent.customer,))
		done = _signup_payment_entry(payment_id)
		if done:
			return frappe._dict(ok=True, reason="already_recorded", **done)

		if payment.get("status") != "paid":
			return frappe._dict(ok=False, reason=payment.get("status") or "unknown_status")
		if (
			cint(payment.get("amount")) != halalas(intent.amount)
			or (payment.get("currency") or "").upper() != "SAR"
		):
			frappe.log_error(
				title="Moyasar: membership amount mismatch",
				message=f"payment {payment_id}: {payment.get('amount')} halalas, expected {halalas(intent.amount)}",
			)
			return frappe._dict(ok=False, reason="amount_mismatch")
		if has_live_membership(intent.customer):
			frappe.log_error(
				title="Moyasar: second membership payment", message=f"payment {payment_id} — refund it"
			)
			return frappe._dict(ok=False, reason="already_member")

		card = _save_card_from_payment(intent.customer, payment)
		subscription = create_subscription(intent.customer, intent.tier)
		invoice = _first_invoice(subscription)

		attempt = frappe.get_doc(
			{
				"doctype": "Membership Charge Attempt",
				"sales_invoice": invoice,
				"customer": intent.customer,
				"payment_method": card,
				"attempt_no": 1,
				"status": PROCESSING,
				"amount": intent.amount,
				"moyasar_payment_id": payment_id,
			}
		).insert(ignore_permissions=True)
		payment_entry = make_payment_entry(invoice, payment_id, flt(intent.amount))
		_set_attempt(attempt, status=SUCCEEDED, payment_entry=payment_entry)

		ensure_portal_user(intent.customer, intent.email)
		frappe.cache.delete_value(SIGNUP_CACHE_KEY + intent_id)

	return frappe._dict(
		ok=True,
		reason="recorded",
		customer=intent.customer,
		subscription=subscription,
		invoice=invoice,
		payment_entry=payment_entry,
		tier=intent.tier,
	)


def _signup_payment_entry(payment_id) -> dict | None:
	row = frappe.db.get_value(
		"Payment Entry",
		{"reference_no": payment_id, "docstatus": 1, "is_membership": 1},
		["name", "party"],
		as_dict=True,
	)
	if not row:
		return None
	return {
		"customer": row.party,
		"payment_entry": row.name,
		"subscription": frappe.db.get_value("Customer", row.party, "membership_subscription"),
	}


def _save_card_from_payment(customer, payment) -> str | None:
	"""Store the token Moyasar returned (save card), after checking it can be charged."""
	token_id = (payment.get("source") or {}).get("token")
	if not token_id:
		frappe.log_error(title="Moyasar: membership payment without a saved card", message=payment.get("id"))
		return None
	return save_card(customer, token_id, source_payment_id=payment.get("id"))


def save_card(customer, token_id, source_payment_id=None) -> str | None:
	token = moyasar.get_client().fetch_token(token_id)
	if (token.get("status") or "").lower() not in CHARGEABLE_TOKEN_STATUSES:
		frappe.log_error(
			title="Moyasar: token cannot be charged", message=f"{token_id}: {token.get('status')}"
		)
		return None
	doc = frappe.get_doc(
		{
			"doctype": "Donor Payment Method",
			"customer": customer,
			"moyasar_token": token_id,
			"brand": token.get("brand"),
			"last4": str(token.get("last_four") or "")[-4:] or None,
			"expiry_month": cint(token.get("month")),
			"expiry_year": cint(token.get("year")),
			"status": CARD_ACTIVE,
			"is_default": 1,
			"source_payment_id": source_payment_id,
		}
	).insert(ignore_permissions=True)
	return doc.name


def create_subscription(customer, tier, start_date=None) -> str:
	"""Native Subscription. On insert ERPNext v16 creates + submits the first invoice
	(posting = due = start date) and moves the period forward (M0 finding)."""
	row = tier_row(tier)
	company = frappe.db.get_single_value("Ataa Settings", "company")
	subscription = frappe.get_doc(
		{
			"doctype": "Subscription",
			"party_type": "Customer",
			"party": customer,
			"company": company,
			"start_date": start_date or nowdate(),
			"generate_invoice_at": "Beginning of the current subscription period",
			"submit_invoice": 1,
			"days_until_due": 0,
			# No pile of unpaid invoices for a suspended member (M0 finding).
			"generate_new_invoices_past_due_date": 0,
			"follow_calendar_months": 0,
			"sales_tax_template": settings().sales_taxes_template,
			"cost_center": frappe.get_cached_value("Company", company, "cost_center"),
			"plans": [{"plan": row.subscription_plan, "qty": 1}],
		}
	)
	subscription.insert(ignore_permissions=True)
	return subscription.name


def _first_invoice(subscription) -> str:
	invoice = frappe.db.get_value(
		"Sales Invoice",
		{"subscription": subscription, "docstatus": 1},
		"name",
		order_by="posting_date asc, creation asc",
	)
	if not invoice:
		frappe.throw(_("لم يُنشئ الاشتراك فاتورته الأولى."))
	return invoice


def ensure_portal_user(customer, email) -> None:
	"""Website User for the donor portal (login by email link), linked through the Contact."""
	if not email:
		return
	user = frappe.db.get_value("User", {"name": email}) or frappe.db.get_value("User", {"email": email})
	if not user:
		user_doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": frappe.db.get_value("Customer", customer, "customer_name"),
				"user_type": "Website User",
				"send_welcome_email": 0,
			}
		)
		user_doc.flags.ignore_permissions = True
		user_doc.insert()
		user = user_doc.name

	contact = frappe.db.get_value("Customer", customer, "customer_primary_contact")
	if contact and not frappe.db.get_value("Contact", contact, "user"):
		frappe.db.set_value("Contact", contact, "user", user, update_modified=False)


# ================================================================ payment entry


def make_payment_entry(invoice, payment_id, amount=None, posting_date=None) -> str:
	"""Payment Entry: Dr Moyasar Clearing / Cr Debtors against the membership invoice."""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	from ataa_hub.ataa_hub.doctype.donation.donation import get_mode_of_payment_account

	ataa = frappe.get_single("Ataa Settings")
	mode = ataa.mop_website
	account = get_mode_of_payment_account(mode, ataa.company)

	pe = get_payment_entry("Sales Invoice", invoice)
	pe.posting_date = posting_date or nowdate()
	pe.mode_of_payment = mode
	pe.paid_to = account
	pe.paid_to_account_currency = frappe.get_cached_value("Account", account, "account_currency")
	pe.reference_no = payment_id
	pe.reference_date = pe.posting_date
	pe.is_membership = 1
	pe.project = ataa.general_project
	pe.remarks = f"Membership payment via Moyasar {payment_id} for {invoice}"

	outstanding = flt(pe.references[0].outstanding_amount) if pe.references else 0
	if amount is not None and flt(amount) != outstanding:
		# The donor paid a different total than the invoice (e.g. a tax template was added later).
		frappe.log_error(
			title="Membership payment differs from invoice",
			message=f"{invoice}: invoice {outstanding}, paid {amount} ({payment_id})",
		)
		paid = min(flt(amount), outstanding)
		pe.paid_amount = pe.received_amount = paid
		pe.references[0].allocated_amount = paid

	pe.flags.ignore_permissions = True
	pe.insert()
	pe.submit()
	return pe.name


# ================================================================ monthly charging


def charge_due_invoices(today=None) -> list[str]:
	"""Daily job: try every unpaid membership invoice that is due (dunning included)."""
	today = getdate(today or nowdate())
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={
			"is_membership": 1,
			"docstatus": 1,
			"outstanding_amount": (">", 0),
			"due_date": ("<=", today),
		},
		order_by="due_date asc",
		pluck="name",
	)
	attempts = []
	with as_administrator():
		for invoice in invoices:
			try:
				attempt = charge_invoice(invoice, today=today)
				if attempt:
					attempts.append(attempt)
				_commit()
			except Exception:
				frappe.db.rollback()
				frappe.log_error(title=f"Membership charge failed for {invoice}")
	return attempts


def charge_invoice(invoice, today=None, force=False) -> str | None:
	"""Charge one invoice once. Returns the attempt name, or None when it must not be charged.

	`force` (card just updated) skips the retry calendar, never the double-charge guard.
	"""
	today = getdate(today or nowdate())
	# Lock the invoice: two workers deciding at the same moment → one charge.
	frappe.db.sql("select name from `tabSales Invoice` where name = %s for update", (invoice,))
	inv = frappe.db.get_value(
		"Sales Invoice",
		invoice,
		["customer", "outstanding_amount", "docstatus", "is_membership", "subscription"],
		as_dict=True,
	)
	if not inv or not inv.is_membership or inv.docstatus != 1 or flt(inv.outstanding_amount) <= 0:
		return None
	if inv.subscription and frappe.db.get_value("Subscription", inv.subscription, "status") == "Cancelled":
		return None  # the donor cancelled: the accountant settles what is left

	attempts = frappe.get_all(
		"Membership Charge Attempt",
		filters={"sales_invoice": invoice},
		fields=["status", "attempt_no", "next_retry_on"],
		order_by="attempt_no desc, creation desc",
	)
	if any(a.status in (PROCESSING, SUCCEEDED, NEEDS_REVIEW) for a in attempts):
		return None  # never charge twice, never guess an unknown result
	failed = [a for a in attempts if a.status == FAILED]
	if not force:
		if len(failed) >= MAX_ATTEMPTS:
			return None  # suspended: waits for a new card
		if failed and failed[0].next_retry_on and getdate(failed[0].next_retry_on) > today:
			return None

	method = get_default_method(inv.customer)
	given_id = str(uuid.uuid4())
	attempt = frappe.get_doc(
		{
			"doctype": "Membership Charge Attempt",
			"sales_invoice": invoice,
			"customer": inv.customer,
			"payment_method": method,
			"attempt_no": len(failed) + 1,
			"status": PROCESSING,
			"amount": flt(inv.outstanding_amount),
			"moyasar_payment_id": given_id if method else None,
		}
	).insert(ignore_permissions=True)

	if not method:
		_fail(attempt, _("لا توجد بطاقة محفوظة."), today)
		return attempt.name

	# The Processing row is saved for good before any money moves.
	_commit()

	client = moyasar.get_client()
	token = frappe.get_doc("Donor Payment Method", method).token()
	try:
		created = client.charge_token(
			given_id=given_id,
			token=token,
			amount_halalas=halalas(inv.outstanding_amount),
			description=f"عضوية عطاء — {invoice}",
			metadata={"invoice": invoice, "attempt": attempt.name},
		)
		# Never trust the create response alone: read the payment back.
		payment = client.fetch_payment(created.get("id") or given_id)
	except moyasar.MoyasarUnavailable:
		frappe.log_error(title=f"Moyasar unavailable while charging {invoice}")
		return attempt.name  # stays Processing → resolve_stale_attempts
	except moyasar.MoyasarError as e:
		_fail(attempt, str(e), today)
		return attempt.name

	apply_payment_result(attempt, payment, today)
	return attempt.name


def apply_payment_result(attempt, payment: dict, today=None) -> None:
	today = getdate(today or nowdate())
	status = payment.get("status")
	if status == "paid":
		if (
			cint(payment.get("amount")) != halalas(attempt.amount)
			or (payment.get("currency") or "").upper() != "SAR"
		):
			_set_attempt(attempt, status=NEEDS_REVIEW, error_message="Amount or currency mismatch")
			_tell_accountants(attempt, _("محاولة خصم عضوية تحتاج مراجعة: {0}"))
			return
		payment_entry = make_payment_entry(attempt.sales_invoice, payment.get("id"), flt(attempt.amount))
		_set_attempt(
			attempt,
			status=SUCCEEDED,
			payment_entry=payment_entry,
			moyasar_payment_id=payment.get("id"),
			next_retry_on=None,
		)
		send_member_email(attempt.customer, "membership_receipt", attempt)
	elif status == "failed":
		message = (payment.get("source") or {}).get("message") or _("رفضت البطاقة العملية.")
		_fail(attempt, message, today)
	# initiated / authorized: stays Processing until Moyasar settles it


def _fail(attempt, message, today) -> None:
	s = settings()
	n = cint(attempt.attempt_no)
	next_retry = None
	if n == 1:
		next_retry = add_days(today, cint(s.first_retry_days) or 3)
	elif n == 2:
		next_retry = add_days(today, cint(s.second_retry_days) or 7)
	_set_attempt(attempt, status=FAILED, error_message=str(message)[:500], next_retry_on=next_retry)

	status = refresh_membership_status(attempt.customer)
	send_member_email(attempt.customer, "membership_payment_failed", attempt, suspended=status == SUSPENDED)
	if status == SUSPENDED:
		_tell_accountants(attempt, _("عضوية موقوفة بعد 3 محاولات خصم فاشلة: {0}"))


def _set_attempt(attempt, **values) -> None:
	attempt.update(values)
	attempt.flags.from_charge_job = True
	attempt.save(ignore_permissions=True)


def _tell_accountants(attempt, subject) -> None:
	name = frappe.db.get_value("Customer", attempt.customer, "customer_name")
	notify(users_with_role(ROLE_ACCOUNTANT), subject.format(name), attempt)


def resolve_stale_attempts(now=None) -> None:
	"""Daily: a Processing attempt is never charged again blindly (PRD §7.5.3 step 7).
	Ask Moyasar what happened; if it cannot tell, hand it to the Accountant."""
	cutoff = add_to_date(now or now_datetime(), minutes=-STALE_PROCESSING_MINUTES)
	stale = frappe.get_all(
		"Membership Charge Attempt",
		filters={"status": PROCESSING, "modified": ("<", cutoff)},
		pluck="name",
	)
	with as_administrator():
		for name in stale:
			attempt = frappe.get_doc("Membership Charge Attempt", name)
			try:
				if not attempt.moyasar_payment_id:
					raise moyasar.MoyasarUnavailable("no payment id")
				payment = moyasar.get_client().fetch_payment(attempt.moyasar_payment_id)
				apply_payment_result(attempt, payment)
				if attempt.status == PROCESSING:
					raise moyasar.MoyasarUnavailable(f"still {payment.get('status')}")
			except moyasar.NotFound:
				# Our given_id never reached Moyasar: nothing was charged.
				_fail(attempt, _("لم تصل العملية إلى ميسّر."), getdate())
			except Exception as e:
				_set_attempt(attempt, status=NEEDS_REVIEW, error_message=str(e)[:500])
				_tell_accountants(attempt, _("محاولة خصم عضوية تحتاج مراجعة: {0}"))
			_commit()


# ================================================================ derived status


def refresh_membership_status(customer: str, today=None) -> str | None:
	c = frappe.db.get_value(
		"Customer", customer, ["membership_subscription", "membership_status", "honorary_since"], as_dict=True
	)
	if not c:
		return None
	status = c.membership_status
	if c.honorary_since:
		status = ACTIVE
	elif c.membership_subscription:
		sub = frappe.db.get_value(
			"Subscription", c.membership_subscription, ["status", "current_invoice_start"], as_dict=True
		)
		open_invoices = open_membership_invoices(customer)
		if sub.status in ("Cancelled", "Completed"):
			# Still a member until the end of the month already paid for.
			paid_through = getdate(sub.current_invoice_start) if sub.current_invoice_start else None
			still_paid = paid_through and getdate(today or nowdate()) < paid_through and not open_invoices
			status = ACTIVE if still_paid else CANCELLED
		else:
			worst = max((failed_attempts(inv) for inv in open_invoices), default=0)
			status = SUSPENDED if worst >= MAX_ATTEMPTS else PAYMENT_PENDING if worst else ACTIVE
	if status != c.membership_status:
		frappe.db.set_value("Customer", customer, "membership_status", status, update_modified=False)
	return status


# ================================================================ doc_events


def new_membership_number() -> str:
	"""16 digits shown on the member's card: prefix + 2-digit year + sequence. Never changes,
	even when the member changes tier."""
	from frappe.model.naming import getseries

	year = getdate(nowdate()).strftime("%y")
	return f"{MEMBERSHIP_NUMBER_PREFIX}{year}{getseries('ATAA-MEMBERSHIP-NO-', 10)}"


def format_membership_number(number: str | None) -> str:
	digits = (number or "").strip()
	return " ".join(digits[i : i + 4] for i in range(0, len(digits), 4))


def on_subscription_update(doc, method=None):
	"""Keep tier / status / subscription on the Customer in line (PRD §9.1)."""
	if doc.party_type != "Customer" or not doc.plans:
		return
	tier = tier_for_plan(doc.plans[0].plan)
	if not tier:
		return
	current = frappe.db.get_value(
		"Customer", doc.party, ["membership_subscription", "honorary_since", "member_since"], as_dict=True
	)
	if current.membership_subscription and current.membership_subscription != doc.name:
		# An old, finished subscription must not take over the current one.
		if doc.status in ("Cancelled", "Completed") or has_live_membership(doc.party):
			return
	values = {"membership_subscription": doc.name}
	if not frappe.db.get_value("Customer", doc.party, "membership_number"):
		values["membership_number"] = new_membership_number()
	if not current.honorary_since:
		values["membership_tier"] = tier
	if not current.member_since:
		values["member_since"] = doc.start_date
	frappe.db.set_value("Customer", doc.party, values, update_modified=False)
	refresh_membership_status(doc.party)


def on_sales_invoice_validate(doc, method=None):
	"""Membership invoices: flag them, book them on GENERAL, tax template from settings."""
	items = membership_items()
	if not any(row.item_code in items for row in doc.items):
		return
	doc.is_membership = 1
	general = frappe.db.get_single_value("Ataa Settings", "general_project")
	doc.project = general
	for row in doc.items:
		row.project = general

	template = settings().sales_taxes_template
	if template and not doc.taxes_and_charges and not doc.get("taxes"):
		doc.taxes_and_charges = template
		doc.append_taxes_from_master()
		doc.calculate_taxes_and_totals()


def on_payment_entry_validate(doc, method=None):
	invoices = [r.reference_name for r in doc.references if r.reference_doctype == "Sales Invoice"]
	if invoices and frappe.db.exists("Sales Invoice", {"name": ("in", invoices), "is_membership": 1}):
		doc.is_membership = 1
		if not doc.project:
			doc.project = frappe.db.get_single_value("Ataa Settings", "general_project")


def on_payment_entry_change(doc, method=None):
	"""Submit or cancel of a membership payment → status and lifetime giving."""
	if not doc.is_membership or doc.party_type != "Customer":
		return
	refresh_membership_status(doc.party)
	update_lifetime_giving(doc.party)


# ================================================================ self-service


def change_tier(customer, tier) -> str:
	"""New plan from the next billing period (the current invoice is already issued)."""
	subscription = _live_subscription(customer)
	row = tier_row(tier)
	if not row:
		frappe.throw(_("اختر مستوى عضوية صحيحاً."))
	if subscription.plans[0].plan == row.subscription_plan:
		frappe.throw(_("أنت مشترك في هذا المستوى بالفعل."))
	subscription.plans[0].plan = row.subscription_plan
	subscription.flags.ignore_permissions = True
	subscription.save()
	return subscription.name


def update_card(customer, token_id) -> dict:
	"""New card becomes the default, old tokens are deleted at Moyasar, and an
	unpaid membership invoice is retried right away."""
	_live_subscription(customer)
	old = frappe.get_all(
		"Donor Payment Method", filters={"customer": customer, "status": CARD_ACTIVE}, pluck="name"
	)
	card = save_card(customer, token_id)
	if not card:
		frappe.throw(_("لم نتمكن من حفظ البطاقة. جرّب بطاقة أخرى."))
	for name in old:
		frappe.get_doc("Donor Payment Method", name).mark_deleted()

	retried = []
	if frappe.db.get_value("Customer", customer, "membership_status") in (PAYMENT_PENDING, SUSPENDED):
		with as_administrator():
			for invoice in open_membership_invoices(customer):
				attempt = charge_invoice(invoice, force=True)
				if attempt:
					retried.append(attempt)
	return {"card": card, "retried": retried, "status": refresh_membership_status(customer)}


def cancel_membership(customer) -> str:
	"""Stop billing now; the donor stays Active until the year already paid ends.

	ERPNext's own `cancel_at_period_end` would still bill one more month here, because
	after the first invoice its "current period" is already the *next* month (M0 finding).
	"""
	return _stop_billing(_live_subscription(customer))


def _stop_billing(subscription) -> str:
	subscription.cancel_at_period_end = 1
	subscription.flags.ignore_permissions = True
	subscription.cancel_subscription()  # status Cancelled, no further invoices
	refresh_membership_status(subscription.party)
	return subscription.current_invoice_start


def close_ended_memberships(today=None) -> None:
	"""Daily: a cancelled membership turns Cancelled once its paid year is over."""
	subscription = frappe.qb.DocType("Subscription")
	customer = frappe.qb.DocType("Customer")
	rows = (
		frappe.qb.from_(customer)
		.join(subscription)
		.on(subscription.name == customer.membership_subscription)
		.select(customer.name)
		.where(
			(customer.membership_status == ACTIVE) & (subscription.status.isin(["Cancelled", "Completed"]))
		)
		.run(pluck=True)
	)
	for name in rows:
		refresh_membership_status(name, today)


def _live_subscription(customer):
	name = frappe.db.get_value("Customer", customer, "membership_subscription")
	if not name or not has_live_membership(customer):
		frappe.throw(_("لا توجد عضوية قائمة."))
	return frappe.get_doc("Subscription", name)


# ================================================================ honorary


def evaluate_honorary(today=None) -> list[str]:
	"""Monthly: donors whose lifetime giving reached the threshold become Honorary."""
	threshold = flt(settings().honorary_threshold)
	if threshold <= 0:
		return []
	customers = frappe.get_all(
		"Customer",
		filters={
			"customer_group": CUSTOMER_GROUP_DONORS,
			"lifetime_giving": (">=", threshold),
			"honorary_since": ("is", "not set"),
		},
		pluck="name",
	)
	with as_administrator():
		for customer in customers:
			grant_honorary_to(customer, today)
			_commit()
	return customers


def grant_honorary_to(customer, today=None) -> None:
	values = {"membership_tier": TIER_HONORARY, "honorary_since": getdate(today or nowdate())}
	if not frappe.db.get_value("Customer", customer, "membership_number"):
		values["membership_number"] = new_membership_number()
	frappe.db.set_value("Customer", customer, values, update_modified=False)
	if settings().honorary_policy == POLICY_CANCEL_PAID and has_live_membership(customer):
		_stop_billing(_live_subscription(customer))
	refresh_membership_status(customer)


@frappe.whitelist(methods=["POST"])
def grant_honorary(customer: str):
	"""Button on Customer: the Executive Director can grant Honorary by hand."""
	frappe.only_for((ROLE_EXECUTIVE, "System Manager"))
	if frappe.db.get_value("Customer", customer, "honorary_since"):
		frappe.throw(_("هذا المتبرع عضو فخري بالفعل."))
	grant_honorary_to(customer)
	return frappe.db.get_value("Customer", customer, ["membership_tier", "honorary_since"], as_dict=True)


# ================================================================ emails


def send_member_email(customer, template, attempt, suspended=False) -> None:
	email = customer_email(customer)
	if not email:
		return
	subjects = {
		"membership_receipt": _("إيصال عضويتك في عطاء"),
		"membership_payment_failed": _("تعذّر خصم اشتراك عضويتك"),
	}
	try:
		frappe.sendmail(
			recipients=[email],
			subject=subjects[template],
			template=template,
			args={
				"customer_name": frappe.db.get_value("Customer", customer, "customer_name"),
				"amount": frappe.utils.fmt_money(attempt.amount, currency="SAR"),
				"invoice": attempt.sales_invoice,
				"next_retry_on": attempt.next_retry_on,
				"suspended": suspended,
				"update_card_url": get_url("/my-giving"),
			},
			reference_doctype=attempt.doctype,
			reference_name=attempt.name,
		)
	except frappe.OutgoingEmailError:
		frappe.clear_last_message()
