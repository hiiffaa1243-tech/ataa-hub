"""Ataa Hub integration API, version 1.

Public contract: API.md and /api-docs (OpenAPI). Endpoints:

    GET  /api/method/ataa_hub.api.v1.list_projects
    POST /api/method/ataa_hub.api.v1.create_donation
    GET  /api/method/ataa_hub.api.v1.get_donation?external_reference=...

Authentication is Frappe's native token auth (`Authorization: token key:secret`).
Frappe resolves the key to a user; this module maps that user to a
`Donation API Client` and applies the client's rules (active, channel, projects).

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

from ataa_hub.constants import CHANNEL_POS, PROJECT_ACTIVE, STATUS_PAID
from ataa_hub.services import get_or_create_donor

SAVEPOINT = "ataa_api_v1"
MAX_TEXT = 140
MAX_AMOUNT = Decimal("1000000")
MAX_METADATA_BYTES = 4096
CLOCK_SKEW = timedelta(minutes=5)
CARD_SCHEMES = ("mada", "visa", "mastercard", "amex")
MOBILE_RE = re.compile(r"^\+9665\d{8}$")
RRN_RE = re.compile(r"^[A-Za-z0-9]{12}$")

DONATION_FIELDS = ["name", "status", "project", "amount", "external_reference", "creation"]


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
	"""Active projects this client may donate to, with their ready-made amounts."""
	return _handle(_list_projects, kwargs)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def create_donation(**kwargs):
	"""Record one successful payment. Safe to retry with the same external_reference."""
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
		# A business rule in a DocType controller refused the record.
		frappe.db.rollback(save_point=SAVEPOINT)
		result = _error(APIError(400, "VALIDATION_ERROR", _clean_message(e), {}))
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.log_error(title="Ataa Hub API v1: unexpected error")
		result = _error(
			APIError(
				500,
				"INTERNAL_ERROR",
				"Unexpected server error. Retry later with the same external_reference.",
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


def _allowed_projects(client_name: str) -> list[str]:
	rows = frappe.db.get_values(
		"API Client Project",
		{"parent": client_name, "parenttype": "Donation API Client"},
		"project",
	)
	return [r[0] for r in rows]


# ================================================================ list_projects


def _list_projects(ctx, payload):
	client = _authenticate(ctx)

	filters = {"status": PROJECT_ACTIVE}
	allowed = _allowed_projects(client.name)
	if allowed:
		filters["name"] = ["in", allowed]

	projects = frappe.get_all(
		"Donation Project",
		filters=filters,
		fields=[
			"name",
			"title",
			"target_amount",
			"collected_amount",
			"progress_percent",
			"allow_custom_amount",
		],
		order_by="title asc",
	)

	options_by_project = {}
	if projects:
		for row in frappe.db.get_values(
			"Donation Option",
			{"parenttype": "Donation Project", "parent": ["in", [p.name for p in projects]]},
			["parent", "label", "amount"],
			as_dict=True,
			order_by="idx asc",
		):
			options_by_project.setdefault(row.parent, []).append(
				{"label": row.label, "amount": flt(row.amount, 2)}
			)

	return _ok(
		[
			{
				"project_code": p.name,
				"title": p.title,
				"target_amount": flt(p.target_amount, 2),
				"collected_amount": flt(p.collected_amount, 2),
				"progress_percent": flt(p.progress_percent, 2),
				"allow_custom_amount": bool(p.allow_custom_amount),
				"donation_options": options_by_project.get(p.name, []),
			}
			for p in projects
		]
	)


# ============================================================== create_donation


def _create_donation(ctx, payload):
	client = _authenticate(ctx)
	data = validate_create_payload(payload, client.channel)

	# 1) Idempotency: same client + same external_reference = same payment.
	existing = _find_donation(client.name, data.external_reference)
	if existing:
		return _replay(existing, data)

	# 2) Project rules.
	project = frappe.db.get_value("Donation Project", data.project_code, ["name", "status"], as_dict=True)
	if not project:
		raise APIError(404, "PROJECT_NOT_FOUND", f"No project with code '{data.project_code}'.")

	allowed = _allowed_projects(client.name)
	if allowed and project.name not in allowed:
		raise APIError(403, "PROJECT_NOT_ALLOWED", f"This client may not donate to project '{project.name}'.")

	if project.status != PROJECT_ACTIVE:
		raise APIError(403, "PROJECT_INACTIVE", f"Project '{project.name}' is not accepting donations.")

	# 3) Record it.
	donor_info = data.donor or {}
	donation = frappe.get_doc(
		{
			"doctype": "Donation",
			"project": project.name,
			"amount": data.amount,
			"channel": client.channel,
			"status": STATUS_PAID,  # the store only calls us after the payment succeeded
			"paid_on": data.paid_on,
			"api_client": client.name,
			"external_reference": data.external_reference,
			"payment_reference": data.payment_reference,
			"donor": get_or_create_donor(
				donor_info.get("name"), donor_info.get("mobile"), donor_info.get("email")
			),
			"donor_name": donor_info.get("name"),
			"raw_payload": _raw_body(payload),
			**(data.pos or {}),
		}
	)
	donation.flags.from_integration = True

	try:
		donation.insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		# Lost a race with an identical request: the UNIQUE index stopped the second insert.
		frappe.local.message_log = []
		existing = _find_donation(client.name, data.external_reference)
		if not existing:
			raise
		return _replay(existing, data)

	return _ok(_serialize(donation.as_dict(), duplicate=False), status=201)


def _find_donation(client_name: str, external_reference: str):
	# FOR UPDATE reads the latest committed row, even inside an older snapshot.
	return frappe.db.get_value(
		"Donation",
		{"api_client": client_name, "external_reference": external_reference},
		DONATION_FIELDS,
		as_dict=True,
		for_update=True,
	)


def _replay(existing, data):
	conflicts = []
	if existing.project != data.project_code:
		conflicts.append("project_code")
	if abs(flt(existing.amount) - flt(data.amount)) >= 0.005:
		conflicts.append("amount")

	if conflicts:
		raise APIError(
			409,
			"DUPLICATE_CONFLICT",
			f"external_reference '{data.external_reference}' was already used with a different "
			+ " and ".join(conflicts)
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
	code = _required_text(payload, "project_code", errors)
	clean.project_code = code.upper() if code else code
	clean.payment_reference = _required_text(payload, "payment_reference", errors)
	clean.amount = _amount(payload.get("amount"), errors)
	clean.paid_on = _paid_at(payload.get("paid_at"), errors)

	currency = payload.get("currency")
	if currency is not None and str(currency).upper() != "SAR":
		errors["currency"] = "Only SAR is accepted."

	clean.donor = _donor(payload.get("donor"), errors)
	clean.pos = _pos(payload.get("pos"), errors) if channel == CHANNEL_POS else None

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


def _required_text(payload, field, errors, prefix=""):
	value = payload.get(field) if isinstance(payload, dict) else None
	key = prefix + field
	if value is None or (isinstance(value, str) and not value.strip()):
		errors[key] = "Required."
		return None
	if not isinstance(value, str | int) or isinstance(value, bool):
		errors[key] = "Must be a string."
		return None
	value = str(value).strip()
	if len(value) > MAX_TEXT:
		errors[key] = f"Max {MAX_TEXT} characters."
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

	mobile = value.get("mobile")
	if mobile is not None and mobile != "":
		mobile = str(mobile).replace(" ", "")
		if not MOBILE_RE.match(mobile):
			errors["donor.mobile"] = "Must be in Saudi format +9665XXXXXXXX."
		else:
			donor["mobile"] = mobile

	email = value.get("email")
	if email is not None and email != "":
		if not isinstance(email, str) or not validate_email_address(email.strip()):
			errors["donor.email"] = "Must be a valid email."
		else:
			donor["email"] = email.strip()
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
	if not isinstance(rrn, str | int) or not RRN_RE.match(str(rrn)):
		errors["pos.rrn"] = "Required for POS clients: exactly 12 letters or digits."
		rrn = None

	return {"terminal_id": terminal_id, "card_scheme": scheme, "rrn": str(rrn) if rrn else None}


# ================================================================ serialization


def _iso(value) -> str | None:
	if not value:
		return None
	return get_datetime(value).replace(tzinfo=ZoneInfo(get_system_timezone())).isoformat(timespec="seconds")


def _serialize(row, duplicate: bool | None = None) -> dict:
	data = {
		"donation_id": row.get("name"),
		"status": row.get("status"),
		"project_code": row.get("project"),
		"amount": flt(row.get("amount"), 2),
		"external_reference": row.get("external_reference"),
	}
	if duplicate is not None:
		data["duplicate"] = duplicate
	data["received_at"] = _iso(row.get("creation"))
	return data
