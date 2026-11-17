import frappe
from frappe import _
from frappe.utils import cint, fmt_money, get_url

from ataa_hub import memberships
from ataa_hub.ataa_hub.doctype.moyasar_settings.moyasar_settings import get_moyasar_config
from ataa_hub.constants import (
	CHANNEL_BANK_TRANSFER,
	CHANNEL_ONLINE_STORE,
	CHANNEL_PARTNER,
	CHANNEL_POS,
	CHANNEL_WEBSITE,
)
from ataa_hub.portal import giving

no_cache = 1

SECTIONS = {
	"overview": "عضويتي",
	"donations": "تبرعاتي",
	"receipts": "الإيصالات",
	"gifts": "الإهداءات",
	"statement": "الكشف السنوي",
}


def get_context(context):
	"""/my-giving[/<section>] — the donor's own membership, donations, receipts, gifts and statement."""
	context.no_cache = 1
	customer = giving.require_donor()
	section = frappe.form_dict.get("section") or "overview"
	if section not in SECTIONS and section not in ("card", "card-callback"):
		raise frappe.DoesNotExistError

	context.csrf_token = frappe.sessions.get_csrf_token()
	context.section = section
	context.sections = SECTIONS
	context.customer_name = frappe.db.get_value("Customer", customer, "customer_name")
	context.money = lambda v: fmt_money(v, currency="SAR")

	if section == "overview":
		context.card = giving.membership_card(customer)
		context.impact = giving.impact_by_project(customer)
		context.recent = giving.donations(customer, limit=5)
	elif section in ("donations", "receipts"):
		f = frappe.form_dict
		context.filters = frappe._dict(
			from_date=f.get("from_date"),
			to_date=f.get("to_date"),
			project=f.get("project"),
			channel=f.get("channel"),
		)
		context.rows = giving.donations(customer, **context.filters)
		context.projects = giving.donor_projects(customer)
		context.channels = [
			CHANNEL_WEBSITE,
			CHANNEL_ONLINE_STORE,
			CHANNEL_POS,
			CHANNEL_BANK_TRANSFER,
			CHANNEL_PARTNER,
		]
	elif section == "gifts":
		context.rows = giving.gifts(customer)
	elif section == "statement":
		context.years = giving.statement_years(customer)
		context.year = cint(frappe.form_dict.get("year")) or context.years[0]
		context.statement = giving.statement(customer, context.year)
	elif section == "card":
		context.publishable_key = get_moyasar_config().publishable_key
		context.callback_url = get_url("/my-giving/card-callback")
	elif section == "card-callback":
		context.card_result = _finish_card_update(customer, frappe.form_dict.get("id"))
	return context


def _finish_card_update(customer, token_id):
	"""Moyasar sends the donor back with ?id=<token>; the token is checked with the secret key."""
	try:
		result = memberships.update_card(customer, token_id)
		frappe.db.commit()  # GET pages are rolled back by default
		return frappe._dict(ok=True, status=result["status"], retried=bool(result["retried"]))
	except frappe.ValidationError as e:
		frappe.db.rollback()
		frappe.clear_last_message()
		return frappe._dict(ok=False, message=str(e))
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="Card update failed")
		return frappe._dict(ok=False, message=_("تعذّر حفظ البطاقة الآن. حاول لاحقاً."))
