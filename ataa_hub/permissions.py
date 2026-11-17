"""Row-level permissions.

Role permissions (who may read/write a DocType at all) live in each DocType JSON.
This module adds the *row* rule from the PRD: a Project Manager only sees the
projects they manage, plus the donations and disbursement requests of those projects.

`*_query_conditions` filter list views, reports, number cards and link searches.
`*_has_permission` protect single documents (opening a URL directly, saving, etc.).
"""

import frappe

from ataa_hub.constants import FULL_VISIBILITY_ROLES, ROLE_PROJECT_MANAGER


def is_restricted_project_manager(user: str | None = None) -> bool:
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	return ROLE_PROJECT_MANAGER in roles and not (roles & FULL_VISIBILITY_ROLES)


def _managed_projects_subquery(user: str) -> str:
	return (
		"(select `tabDonation Project`.name from `tabDonation Project` "
		f"where `tabDonation Project`.project_manager = {frappe.db.escape(user)})"
	)


# ---------------------------------------------------------------- list filters


def project_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if is_restricted_project_manager(user):
		return f"`tabDonation Project`.project_manager = {frappe.db.escape(user)}"
	return ""


def donation_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if is_restricted_project_manager(user):
		return f"`tabDonation`.project in {_managed_projects_subquery(user)}"
	return ""


def disbursement_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if is_restricted_project_manager(user):
		return f"`tabDisbursement Request`.project in {_managed_projects_subquery(user)}"
	return ""


# ------------------------------------------------------------ document checks


def _manages(project: str | None, user: str) -> bool:
	if not project:
		# New document without a project yet: mandatory validation will catch it.
		return True
	return frappe.db.get_value("Donation Project", project, "project_manager") == user


def project_has_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	user = user or frappe.session.user
	if not is_restricted_project_manager(user):
		return True
	return not doc.project_manager or doc.project_manager == user


def donation_has_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	user = user or frappe.session.user
	if not is_restricted_project_manager(user):
		return True
	return _manages(doc.project, user)


def disbursement_has_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	user = user or frappe.session.user
	if not is_restricted_project_manager(user):
		return True
	return _manages(doc.project, user)
