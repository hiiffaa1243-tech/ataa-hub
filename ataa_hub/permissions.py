"""Row-level permissions (PRD §8).

Role permissions (who may read/write a DocType at all) live in the DocType JSON.
This module adds two row rules:
- a Project Manager only sees the projects they are assigned to (ERPNext's native
  Project → Users table), plus those projects' donations, disbursement requests and
  fund allocations;
- a portal donor (Website User) only sees the donations, invoices, payments and
  saved cards of the Customer(s) linked to their Contact (PRD §7.7).

`*_query_conditions` filter list views, reports and link searches.
`*_has_permission` protect single documents (direct URL, save, print...).
On Frappe v16 a hook must return True for "no objection": None counts as a denial.
"""

import frappe

from ataa_hub.constants import (
	FULL_VISIBILITY_ROLES,
	PROJECT_EDITOR_ROLES,
	ROLE_API_CLIENT,
	ROLE_PROJECT_MANAGER,
)

WRITE_PTYPES = {"write", "create", "delete", "submit", "cancel", "amend"}


def is_restricted_project_manager(user: str | None = None) -> bool:
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	return ROLE_PROJECT_MANAGER in roles and not (roles & FULL_VISIBILITY_ROLES)


def _assigned_projects_sql(user: str) -> str:
	return f"(select `tabProject User`.parent from `tabProject User` where `tabProject User`.user = {frappe.db.escape(user)})"


def assigned_projects(user: str) -> set[str]:
	return set(
		frappe.get_all("Project User", filters={"user": user, "parenttype": "Project"}, pluck="parent")
	)


# ---------------------------------------------------------------- list filters


def project_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if is_restricted_project_manager(user):
		return f"`tabProject`.name in {_assigned_projects_sql(user)}"
	return ""


def _by_project(table: str, field: str, user: str | None) -> str:
	user = user or frappe.session.user
	if is_restricted_project_manager(user):
		return f"`tab{table}`.`{field}` in {_assigned_projects_sql(user)}"
	return ""


def is_portal_user(user: str | None = None) -> bool:
	"""A donor using the portal. API integration users are Website Users too, but
	their access is decided by their Donation API Client, not by this rule."""
	user = user or frappe.session.user
	if user == "Guest":
		return True
	if frappe.get_cached_value("User", user, "user_type") != "Website User":
		return False
	return ROLE_API_CLIENT not in frappe.get_roles(user)


def _donor_customers_sql(user: str) -> str:
	return (
		"(select dl.link_name from `tabDynamic Link` dl"
		" join `tabContact` c on c.name = dl.parent"
		" where dl.parenttype = 'Contact' and dl.link_doctype = 'Customer'"
		f" and c.user = {frappe.db.escape(user)})"
	)


def _by_donor(table: str, field: str, user: str | None) -> str:
	user = user or frappe.session.user
	if is_portal_user(user):
		return f"`tab{table}`.`{field}` in {_donor_customers_sql(user)}"
	return ""


def donation_query_conditions(user: str | None = None) -> str:
	return _by_donor("Donation", "donor", user) or _by_project("Donation", "project", user)


def sales_invoice_query_conditions(user: str | None = None) -> str:
	return _by_donor("Sales Invoice", "customer", user)


def payment_entry_query_conditions(user: str | None = None) -> str:
	return _by_donor("Payment Entry", "party", user)


def payment_method_query_conditions(user: str | None = None) -> str:
	return _by_donor("Donor Payment Method", "customer", user)


def disbursement_query_conditions(user: str | None = None) -> str:
	return _by_project("Disbursement Request", "project", user)


def fund_allocation_query_conditions(user: str | None = None) -> str:
	return _by_project("Fund Allocation", "to_project", user)


# ------------------------------------------------------------ document checks


def project_has_permission(doc, ptype=None, user=None, **kwargs):
	user = user or frappe.session.user
	if ptype in WRITE_PTYPES and not (set(frappe.get_roles(user)) & PROJECT_EDITOR_ROLES):
		return False  # accountant / executive see projects but don't edit them (PRD §8)
	if not is_restricted_project_manager(user) or doc.is_new():
		return True  # no extra rule; role permissions still decide
	return doc.name in assigned_projects(user)


def _doc_in_assigned_project(doc, field: str, user) -> bool:
	user = user or frappe.session.user
	if not is_restricted_project_manager(user):
		return True
	project = doc.get(field)
	if doc.is_new() and not project:
		return True  # empty new form: the project is checked again on save
	return bool(project) and project in assigned_projects(user)


def _portal_check(doc, field, ptype, user):
	user = user or frappe.session.user
	if not is_portal_user(user):
		return None
	if ptype in WRITE_PTYPES:
		return False
	from ataa_hub.portal.giving import customers_for_user

	return bool(doc.get(field)) and doc.get(field) in customers_for_user(user)


def donation_has_permission(doc, ptype=None, user=None, **kwargs):
	portal = _portal_check(doc, "donor", ptype, user)
	if portal is not None:
		return portal
	return _doc_in_assigned_project(doc, "project", user)


def sales_invoice_has_permission(doc, ptype=None, user=None, **kwargs):
	portal = _portal_check(doc, "customer", ptype, user)
	return True if portal is None else portal


def payment_entry_has_permission(doc, ptype=None, user=None, **kwargs):
	portal = _portal_check(doc, "party", ptype, user)
	return True if portal is None else portal


def payment_method_has_permission(doc, ptype=None, user=None, **kwargs):
	portal = _portal_check(doc, "customer", ptype, user)
	return True if portal is None else portal


def disbursement_has_permission(doc, ptype=None, user=None, **kwargs):
	return _doc_in_assigned_project(doc, "project", user)


def fund_allocation_has_permission(doc, ptype=None, user=None, **kwargs):
	return _doc_in_assigned_project(doc, "to_project", user)
