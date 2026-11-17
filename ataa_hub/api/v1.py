"""Ataa Hub integration API — contract v2 on the v1 path (API.md, /api-docs).

    GET  /api/method/ataa_hub.api.v1.list_projects[?event_code=...]
    POST /api/method/ataa_hub.api.v1.create_donation
    GET  /api/method/ataa_hub.api.v1.get_donation?external_reference=...

Authentication is Frappe's native token auth (`Authorization: token key:secret`).
Frappe resolves the key to a user; this module maps that user to a
`Donation API Client` and applies the client's rules (active, channel, projects).

`create_donation` creates **and submits** a Donation in one transaction, so the
Journal Entry is posted before the response is sent. If anything fails, the whole
request is rolled back to a savepoint and nothing is saved.

Every response body is {"ok": true, "data": ...} or
{"ok": false, "error": {"code", "message", "details"}}, with a real HTTP status code.
"""

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import flt, get_datetime, get_system_timezone, now_datetime, validate_email_address

from ataa_hub.ataa_hub.doctype.donation.donation import gift_url, receipt_verification_url
from ataa_hub.constants import CHANNEL_POS
from ataa_hub.donors import get_or_create_donor, is_valid_mobile, normalize_mobile
from ataa_hub.projects import PUBLIC_FILTERS, list_public_projects

SAVEPOINT = "ataa_api_v1"
MAX_TEXT = 140
MAX_GIFT_MESSAGE = 500
MAX_AMOUNT = Decimal("1000000")
MAX_METADATA_BYTES = 4096
CLOCK_SKEW = timedelta(minutes=5)
CARD_SCHEMES = ("mada", "visa", "mastercard", "amex")
OCCASIONS = ("Eid", "Ramadan", "Wedding", "Newborn", "Graduation", "In Memory", "Other")
RRN_RE = re.compile(r"^[A-Za-z0-9]{12}$")

DONATION_FIELDS = [
	"name",
	"docstatus",
	"payment_status",
	"project",
	"amount",
	"external_reference",
	"creation",
	"impact_units",
	"impact_unit_label",
	"fundraising_event",
	"is_gift",
	"recipient_name",
	"recipient_mobile",
	"recipient_email",
	"gift_token",
	"gift_email_sent",
	"receipt_token",
]


class APIError(Exception):
	def __init__(self, http_status: int, code: str, message: str, details: dict | None = None):
		super().__init__(message)
		self.http_status = http_status
		self.code = code
		self.message = message
		self.details = details or {}


# =================================================================== endpoints


@frappe.whitelist(allow_guest=True, methods=["GET"])
def list_projects(**kwargs):
	"""Projects this client may donate to now, optionally only those of one event."""
	return _handle(_list_projects, kwargs)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def create_donation(**kwargs):
	"""Record and post one successful payment. Safe to retry with the same external_reference."""
	return _handle(_create_donation, kwargs)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_donation(**kwargs):
	"""Check whether a donation sent by this client was recorded."""
	return _handle(_get_donation, kwargs)


# ============================================================ request handling


def _handle(handler, kwargs: dict):
	"""Shared envelope: auth errors, rollback on failure, status codes, audit timestamp.

	`allow_guest=True` is deliberate: without it Frappe answers a missing key with 403.
	Here a missing key returns 401 like a wrong key does (wrong keys are rejected by
	Frappe itself before this code runs).
	"""
	payload = {k: v for k, v in kwargs.items() if k != "cmd"}
	ctx = frappe._dict(client=None)

	frappe.db.savepoint(SAVEPOINT)
	try:
		result = handler(ctx, payload)
	except APIError as e:
		frappe.db.rollback(save_point=SAVEPOINT)
		result = _error(e)
	except frappe.ValidationError as e:
		# A business rule in a DocType controller (Donation, Journal Entry...) refused the record.
		frappe.db.rollback(save_point=SAVEPOINT)
		result = _error(APIError(400, "VALIDATION_ERROR", _clean_message(e), {}))
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.log_error(title="Ataa Hub API: unexpected error")
		result = _error(
			APIError(
				500,
				"INTERNAL_ERROR",
				"Unexpected server error. Nothing was saved. Retry later with the same external_reference.",
			)
		)

	# Messages raised by frappe.throw would otherwise be appended to the body as `_server_messages`.
	frappe.local.message_log = []

	if ctx.client:
		frappe.db.set_value(
			"Donation API Client", ctx.client.name, "last_request_on", now_datetime(), update_modified=False
		)
	# GET requests are rolled back by Frappe by default; keep the audit timestamp.
	frappe.local.flags.commit = True
	return result


def _ok(data, status: int = 200) -> dict:
	frappe.local.response["http_status_code"] = status
	return {"ok": True, "data": data}


def _error(e: APIError) -> dict:
	frappe.local.response["http_status_code"] = e.http_status
	return {"ok": False, "error": {"code": e.code, "message": e.message, "details": e.details}}


def _clean_message(e: Exception) -> str:
	return re.sub(r"<[^>]+>", "", str(e)).strip() or "Validation failed."


def _authenticate(ctx) -> frappe._dict:
	user = frappe.session.user
	if not user or user == "Guest":
		raise APIError(
			401,
			"AUTH_REQUIRED",
			"Missing credentials. Send header: Authorization: token {api_key}:{api_secret}",
		)

	client = frappe.db.get_value(
		"Donation API Client",
		{"integration_user": user},
		["name", "client_name", "channel", "is_active"],
		as_dict=True,
	)
	if not client:
		raise APIError(403, "NOT_AN_API_CLIENT", "These credentials do not belong to an API Client.")

	ctx.client = client
	if not client.is_active:
		raise APIError(403, "CLIENT_INACTIVE", "This API Client has been deactivated by the association.")
	return client


def _allowed_projects(client_name: str) -> set[str]:
	return set(
		frappe.get_all(
			"API Client Project",
			filters={"parent": client_name, "parenttype": "Donation API Client"},
			pluck="project",
		)
	)


def _event_not_active(code: str) -> APIError:
	# Same answer for unknown, not active and out-of-window: the API does not reveal which events exist.
	return APIError(
		403, "EVENT_NOT_ACTIVE", f"Event '{code}' is not accepting donations now.", {"event_code": code}
	)


def _load_event(code: str):
	if not frappe.db.exists("Fundraising Event", code):
		raise _event_not_active(code)
	return frappe.get_doc("Fundraising Event", code)


# ================================================================ list_projects


def _list_projects(ctx, payload):
	client = _authenticate(ctx)
	names = _allowed_projects(client.name) or None

	event_code = _clean_code(payload.get("event_code"))
	if event_code:
		event = _load_event(event_code)
		if event.status != "Active":
			raise _event_not_active(event_code)
		names = event.project_names & names if names is not None else event.project_names

	# None = no restriction; an empty set = nothing allowed.
	return _ok([_project_out(p) for p in list_public_projects(sorted(names) if names is not None else None)])


def _project_out(p) -> dict:
	return {
		"project_code": p.code,
		"title": p.title,
		"fund_type": p.fund_type,
		"target_amount": flt(p.target_amount, 2),
		"collected_amount": flt(p.collected_amount, 2),
		"progress_percent": flt(p.progress_percent, 2) if p.progress_percent is not None else None,
		"impact_unit_label": p.impact_unit_label,
		"impact_units_per_sar": flt(p.impact_units_per_sar),
		"allow_custom_amount": bool(p.allow_custom_amount),
		"donation_options": [{"label": o.label, "amount": o.amount} for o in p.options],
	}


# ============================================================== create_donation


def _create_donation(ctx, payload):
	client = _authenticate(ctx)
	data = validate_create_payload(payload, client.channel)
	key = f"{client.name}:{data.external_reference}"

	# 1) Idempotency: same client + same external_reference = same payment.
	existing = _find_donation(key)
	if existing:
		return _replay(existing, data)

	# 2) Project rules.
	project = frappe.db.get_value("Project", {"project_code": data.project_code}, "name")
	if not project:
		raise APIError(404, "PROJECT_NOT_FOUND", f"No project with code '{data.project_code}'.")

	allowed = _allowed_projects(client.name)
	if allowed and project not in allowed:
		raise APIError(
			403, "PROJECT_NOT_ALLOWED", f"This client may not donate to project '{data.project_code}'."
		)

	if not frappe.db.exists("Project", {"name": project, **PUBLIC_FILTERS}):
		raise APIError(403, "PROJECT_INACTIVE", f"Project '{data.project_code}' is not accepting donations.")

	# 3) Event rules (API.md §5.2.2), in this order.
	if data.event_code:
		_check_event(client, data, project)

	# 4) Record and post it, in this transaction.
	donation = _build_donation(client, data, project, key, payload)
	try:
		donation.insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		# Lost a race with an identical request: the UNIQUE index stopped the second insert.
		frappe.local.message_log = []
		existing = _find_donation(key)
		if not existing:
			raise
		return _replay(existing, data)

	donation.submit()
	return _ok(_serialize(donation.as_dict(), duplicate=False), status=201)


def _check_event(client, data, project: str):
	event = _load_event(data.event_code)
	if not event.is_open_at(data.paid_at):
		raise _event_not_active(data.event_code)

	if client.channel == CHANNEL_POS:
		terminal_id = data.pos["terminal_id"]
		if not event.has_terminal(client.name, terminal_id):
			raise APIError(
				403,
				"TERMINAL_NOT_IN_EVENT",
				f"Terminal '{terminal_id}' is not registered on event '{data.event_code}'.",
				{"event_code": data.event_code, "terminal_id": terminal_id},
			)

	if project not in event.project_names:
		raise APIError(
			403,
			"PROJECT_NOT_ALLOWED",
			f"Project '{data.project_code}' is not part of event '{data.event_code}'.",
			{"event_code": data.event_code, "project_code": data.project_code},
		)


def _build_donation(client, data, project: str, key: str, payload: dict):
	donor = data.donor or {}
	gift = data.gift or {}
	donation = frappe.get_doc(
		{
			"doctype": "Donation",
			"project": project,
			"amount": data.amount,
			"channel": client.channel,  # from the client, never from the body
			"posting_date": data.paid_at.date(),
			"paid_at": data.paid_at,
			"api_client": client.name,
			"external_reference": data.external_reference,
			"idempotency_key": key,
			"payment_reference": data.payment_reference,
			"fundraising_event": data.event_code,
			"donor": get_or_create_donor(donor.get("name"), donor.get("mobile"), donor.get("email")),
			"donor_name": donor.get("name"),
			"donor_mobile": donor.get("mobile"),
			"donor_email": donor.get("email"),
			"is_gift": 1 if gift else 0,
			"recipient_name": gift.get("recipient_name"),
			"recipient_mobile": gift.get("recipient_mobile"),
			"recipient_email": gift.get("recipient_email"),
			"occasion": gift.get("occasion") or "Other",
			"gift_message": gift.get("message"),
			"show_amount_on_gift": 1 if gift.get("show_amount") else 0,
			"raw_payload": _raw_body(payload),
			**(data.pos or {}),
		}
	)
	donation.flags.from_integration = True
	return donation


def _find_donation(key: str):
	# FOR UPDATE reads the latest committed row, even inside an older snapshot.
	return frappe.db.get_value(
		"Donation", {"idempotency_key": key}, DONATION_FIELDS, as_dict=True, for_update=True
	)


def _replay(existing, data):
	conflicts = []
	if _project_code(existing.project) != data.project_code:
		conflicts.append("project_code")
	if abs(flt(existing.amount) - flt(data.amount)) >= 0.005:
		conflicts.append("amount")
	if (existing.fundraising_event or None) != data.event_code:
		conflicts.append("event_code")
	gift = data.gift or {}
	sent = (gift.get("recipient_name"), gift.get("recipient_mobile"), gift.get("recipient_email"))
	stored = (
		(existing.recipient_name, existing.recipient_mobile, existing.recipient_email)
		if existing.is_gift
		else (None, None, None)
	)
	if tuple(v or None for v in sent) != tuple(v or None for v in stored):
		conflicts.append("gift")

	if conflicts:
		raise APIError(
			409,
			"DUPLICATE_CONFLICT",
			f"external_reference '{data.external_reference}' was already used with a different "
			+ ", ".join(conflicts)
			+ ".",
			{"donation_id": existing.name, "conflicting_fields": conflicts},
		)
	return _ok(_serialize(existing, duplicate=True), status=200)


def _raw_body(payload: dict) -> str:
	request = getattr(frappe.local, "request", None)
	if request is not None:
		body = request.get_data(as_text=True)
		if body:
			return body
	return json.dumps(payload, ensure_ascii=False, default=str)


# ================================================================= get_donation


def _get_donation(ctx, payload):
	client = _authenticate(ctx)
	reference = payload.get("external_reference")
	if not isinstance(reference, str) or not reference.strip():
		raise APIError(
			400, "VALIDATION_ERROR", "Request has 1 invalid field.", {"external_reference": "Required."}
		)

	row = frappe.db.get_value(
		"Donation",
		{"api_client": client.name, "external_reference": reference.strip()},
		DONATION_FIELDS,
		as_dict=True,
	)
	if not row:
		raise APIError(
			404,
			"DONATION_NOT_FOUND",
			f"No donation with external_reference '{reference.strip()}' for this client.",
		)
	return _ok(_serialize(row))


# ================================================================== validation


def validate_create_payload(payload: dict, channel: str) -> frappe._dict:
	"""Check every field and report *all* problems at once (400 VALIDATION_ERROR)."""
	errors: dict[str, str] = {}
	clean = frappe._dict()

	clean.external_reference = _required_text(payload, "external_reference", errors)
	clean.project_code = _clean_code(_required_text(payload, "project_code", errors))
	clean.payment_reference = _required_text(payload, "payment_reference", errors)
	clean.amount = _amount(payload.get("amount"), errors)
	clean.paid_at = _paid_at(payload.get("paid_at"), errors)

	currency = payload.get("currency")
	if currency is not None and str(currency).upper() != "SAR":
		errors["currency"] = "Only SAR is accepted."

	clean.donor = _donor(payload.get("donor"), errors)
	clean.pos = _pos(payload.get("pos"), errors) if channel == CHANNEL_POS else None
	clean.gift = _gift(payload.get("gift"), errors)

	event_code = payload.get("event_code")
	clean.event_code = None
	if event_code not in (None, ""):
		if not isinstance(event_code, str) or len(event_code.strip()) > MAX_TEXT:
			errors["event_code"] = f"Must be a string of max {MAX_TEXT} characters."
		else:
			clean.event_code = _clean_code(event_code)

	metadata = _as_object(payload.get("metadata"))
	if payload.get("metadata") is not None:
		if not isinstance(metadata, dict):
			errors["metadata"] = "Must be an object."
		elif len(json.dumps(metadata, ensure_ascii=False).encode()) > MAX_METADATA_BYTES:
			errors["metadata"] = "Max 4 KB."

	if errors:
		count = len(errors)
		raise APIError(
			400, "VALIDATION_ERROR", f"Request has {count} invalid field{'s' if count > 1 else ''}.", errors
		)
	return clean


def _clean_code(value) -> str | None:
	return value.strip().upper() if isinstance(value, str) and value.strip() else None


def _required_text(payload, field, errors, prefix="", max_len=MAX_TEXT):
	value = payload.get(field) if isinstance(payload, dict) else None
	key = prefix + field
	if value is None or (isinstance(value, str) and not value.strip()):
		errors[key] = "Required."
		return None
	if not isinstance(value, str | int) or isinstance(value, bool):
		errors[key] = "Must be a string."
		return None
	value = str(value).strip()
	if len(value) > max_len:
		errors[key] = f"Max {max_len} characters."
		return None
	return value


def _amount(value, errors):
	if value is None:
		errors["amount"] = "Required."
		return None
	if isinstance(value, bool) or not isinstance(value, int | float | str):
		errors["amount"] = "Must be a number."
		return None
	try:
		amount = Decimal(str(value))
	except InvalidOperation:
		errors["amount"] = "Must be a number."
		return None
	if not amount.is_finite():
		errors["amount"] = "Must be a number."
	elif amount <= 0:
		errors["amount"] = "Must be greater than 0."
	elif amount != amount.quantize(Decimal("0.01")):
		errors["amount"] = "Max 2 decimal places."
	elif amount > MAX_AMOUNT:
		errors["amount"] = f"Must not exceed {MAX_AMOUNT}."
	else:
		return float(amount)
	return None


def _paid_at(value, errors):
	if not isinstance(value, str) or not value.strip():
		errors["paid_at"] = "Required. ISO 8601 with timezone, e.g. 2026-11-17T15:42:10+03:00."
		return None
	try:
		moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
	except ValueError:
		errors["paid_at"] = "Must be ISO 8601, e.g. 2026-11-17T15:42:10+03:00."
		return None
	if moment.tzinfo is None:
		errors["paid_at"] = "Timezone offset is required, e.g. +03:00."
		return None

	# Store in the site's timezone (Asia/Riyadh), as Frappe Datetime fields are naive.
	local = moment.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
	if local > now_datetime() + CLOCK_SKEW:
		errors["paid_at"] = "Cannot be in the future."
		return None
	return local


def _as_object(value):
	if isinstance(value, str):
		try:
			return json.loads(value)
		except ValueError:
			return value
	return value


def _mobile(value, key, errors):
	if value is None or value == "":
		return None
	mobile = normalize_mobile(str(value))
	if not is_valid_mobile(mobile):
		errors[key] = "Must be in Saudi format +9665XXXXXXXX."
		return None
	return mobile


def _email(value, key, errors):
	if value is None or value == "":
		return None
	if not isinstance(value, str) or not validate_email_address(value.strip()):
		errors[key] = "Must be a valid email."
		return None
	return value.strip()


def _donor(value, errors):
	value = _as_object(value)
	if value is None:
		return None
	if not isinstance(value, dict):
		errors["donor"] = "Must be an object."
		return None

	donor = {}
	name = value.get("name")
	if name is not None:
		if not isinstance(name, str) or len(name.strip()) > MAX_TEXT:
			errors["donor.name"] = f"Must be a string of max {MAX_TEXT} characters."
		else:
			donor["name"] = name.strip() or None
	donor["mobile"] = _mobile(value.get("mobile"), "donor.mobile", errors)
	donor["email"] = _email(value.get("email"), "donor.email", errors)
	return donor


def _pos(value, errors):
	value = _as_object(value)
	if not isinstance(value, dict):
		errors["pos"] = "Required for POS clients."
		return None

	terminal_id = _required_text(value, "terminal_id", errors, prefix="pos.")

	scheme = value.get("card_scheme")
	if not isinstance(scheme, str) or scheme.strip().lower() not in CARD_SCHEMES:
		errors["pos.card_scheme"] = "Must be one of: " + ", ".join(CARD_SCHEMES) + "."
		scheme = None
	else:
		scheme = scheme.strip().lower()

	rrn = value.get("rrn")
	if not isinstance(rrn, str | int) or isinstance(rrn, bool) or not RRN_RE.match(str(rrn)):
		errors["pos.rrn"] = "Required for POS clients: exactly 12 letters or digits."
		rrn = None

	return {"terminal_id": terminal_id, "card_scheme": scheme, "rrn": str(rrn) if rrn else None}


def _gift(value, errors):
	value = _as_object(value)
	if value is None:
		return None
	if not isinstance(value, dict):
		errors["gift"] = "Must be an object."
		return None

	gift = {"recipient_name": _required_text(value, "recipient_name", errors, prefix="gift.")}
	gift["recipient_mobile"] = _mobile(value.get("recipient_mobile"), "gift.recipient_mobile", errors)
	gift["recipient_email"] = _email(value.get("recipient_email"), "gift.recipient_email", errors)
	if (
		not gift["recipient_mobile"]
		and not gift["recipient_email"]
		and "gift.recipient_mobile" not in errors
		and "gift.recipient_email" not in errors
	):
		errors["gift.recipient_email"] = "At least one of recipient_mobile or recipient_email is required."

	occasion = value.get("occasion") or "Other"
	if occasion not in OCCASIONS:
		errors["gift.occasion"] = "Must be one of: " + ", ".join(OCCASIONS) + "."
	gift["occasion"] = occasion

	message = value.get("message")
	if message is not None:
		if not isinstance(message, str) or len(message) > MAX_GIFT_MESSAGE:
			errors["gift.message"] = f"Must be a string of max {MAX_GIFT_MESSAGE} characters."
		else:
			gift["message"] = message.strip() or None

	show_amount = value.get("show_amount", False)
	if not isinstance(show_amount, bool):
		errors["gift.show_amount"] = "Must be true or false."
	gift["show_amount"] = show_amount is True
	return gift


# ================================================================ serialization


def _iso(value) -> str | None:
	if not value:
		return None
	return get_datetime(value).replace(tzinfo=ZoneInfo(get_system_timezone())).isoformat(timespec="seconds")


def _project_code(project: str | None) -> str | None:
	return frappe.db.get_value("Project", project, "project_code") if project else None


def _serialize(row, duplicate: bool | None = None) -> dict:
	status = "Refunded" if row.get("docstatus") == 2 else (row.get("payment_status") or "Paid")
	data = {
		"donation_id": row.get("name"),
		"status": status,
		"project_code": _project_code(row.get("project")),
		"amount": flt(row.get("amount"), 2),
		"external_reference": row.get("external_reference"),
	}
	if duplicate is not None:
		data["duplicate"] = duplicate
	data.update(
		{
			"received_at": _iso(row.get("creation")),
			"impact_units": flt(row.get("impact_units"), 2),
			"impact_unit_label": row.get("impact_unit_label"),
			"event_code": row.get("fundraising_event") or None,
			"gift": (
				{"url": gift_url(row.get("gift_token")), "email_sent": bool(row.get("gift_email_sent"))}
				if row.get("is_gift")
				else None
			),
			"receipt_verification_url": receipt_verification_url(row.get("receipt_token")),
		}
	)
	return data
