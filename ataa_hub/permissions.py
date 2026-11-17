"""Row-level permissions (PRD §8).

Role permissions (who may read/write a DocType at all) live in the DocType JSON.
This module adds the row rule: a Project Manager only sees the projects they are
assigned to (ERPNext's native Project → Users table), plus those projects'
donations (and, from M4, disbursement requests).

`*_query_conditions` filter list views, reports and link searches.
`*_has_permission` protect single documents (direct URL, save, print...).
"""

import frappe

from ataa_hub.constants import FULL_VISIBILITY_ROLES, ROLE_PROJECT_MANAGER


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


def donation_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if is_restricted_project_manager(user):
		return f"`tabDonation`.project in {_assigned_projects_sql(user)}"
	return ""


# ------------------------------------------------------------ document checks


def project_has_permission(doc, ptype=None, user=None, **kwargs):
	user = user or frappe.session.user
	if not is_restricted_project_manager(user) or doc.is_new():
		return None  # fall back to the normal role permissions
	return doc.name in assigned_projects(user)


def donation_has_permission(doc, ptype=None, user=None, **kwargs):
	user = user or frappe.session.user
	if not is_restricted_project_manager(user):
		return None
	return bool(doc.project) and doc.project in assigned_projects(user)
