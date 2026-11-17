"""Membership self-service endpoints (PRD §7.5.4, §9.3).

The donor is always taken from the logged-in portal user, never from a parameter,
so nobody can change someone else's membership.
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from ataa_hub import memberships


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=10 * 60)
def start_signup(tier=None, full_name=None, email=None, mobile=None):
	return memberships.start_signup_for(tier, full_name, email, mobile)


def _my_customer() -> str:
	customer = memberships.customer_for_user()
	if not customer:
		frappe.throw(_("سجّل الدخول بحساب المتبرع أولاً."), frappe.PermissionError)
	return customer


@frappe.whitelist(methods=["POST"])
def change_tier(tier=None):
	return memberships.change_tier(_my_customer(), tier)


@frappe.whitelist(methods=["POST"])
def update_card(token_id=None):
	if not token_id:
		frappe.throw(_("لم تصل بيانات البطاقة الجديدة."))
	return memberships.update_card(_my_customer(), token_id)


@frappe.whitelist(methods=["POST"])
def cancel_membership():
	return {"ends_after": memberships.cancel_membership(_my_customer())}
