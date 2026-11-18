"""Desk boot for staff: one product, not two apps side by side.

Staff (Executive Director, Accountant, Project Manager) work in عطاء only, so the ERPNext tile
is taken off their apps screen and their desk home is our sidebar. ERPNext pages they need
(a Project, a Journal Entry, the General Ledger) still open from our sidebar and dashboard.
System Managers keep the full ERPNext desk for configuration.

Done through Frappe's `extend_bootinfo` hook; ERPNext and Frappe code are untouched.
"""

import frappe

from ataa_hub.constants import ROLE_ACCOUNTANT, ROLE_EXECUTIVE, ROLE_PROJECT_MANAGER

STAFF_ROLES = {ROLE_EXECUTIVE, ROLE_ACCOUNTANT, ROLE_PROJECT_MANAGER}
HIDDEN_APPS = {"erpnext", "frappe"}
OUR_SHELL = "Ataa Hub"


def is_staff_only(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return False
	roles = set(frappe.get_roles(user))
	return bool(roles & STAFF_ROLES) and "System Manager" not in roles


def extend_bootinfo(bootinfo):
	if not is_staff_only():
		return
	bootinfo.ataa_staff = 1
	for app in bootinfo.get("app_data") or []:
		if app.get("app_name") in HIDDEN_APPS:
			app["on_apps_screen"] = False
	sidebar = (bootinfo.get("module_sidebars") or {}).get(OUR_SHELL)
	if sidebar:
		bootinfo.home_shell = OUR_SHELL
		sidebar["items"] = drop_empty_sections(sidebar.get("items") or [])


def drop_empty_sections(items):
	"""Items are already filtered by permission; a heading left with no links under it goes too."""
	kept = []
	for i, item in enumerate(items):
		if item.get("type") == "Section Break":
			nxt = items[i + 1] if i + 1 < len(items) else None
			if not (nxt and nxt.get("child") and nxt.get("type") != "Section Break"):
				continue
		kept.append(item)
	return kept
