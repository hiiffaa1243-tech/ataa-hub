"""Small helpers that create fake records for tests."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_system_timezone


def make_user(email: str, *roles: str) -> str:
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
		missing = [r for r in roles if r not in frappe.get_roles(email)]
		if missing:
			user.add_roles(*missing)
	else:
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
	return email


def make_project(code: str, status: str = "Active", target: float = 100000, manager: str = "Administrator"):
	if not frappe.db.exists("Donation Project", code):
		frappe.get_doc(
			{
				"doctype": "Donation Project",
				"project_code": code,
				"title": f"Test project {code}",
				"target_amount": target,
				"project_manager": manager,
				"status": "Active",
				"allow_custom_amount": 1,
				"donation_options": [{"label": "Option 100", "amount": 100}],
			}
		).insert(ignore_permissions=True)
	frappe.db.set_value("Donation Project", code, {"status": status, "project_manager": manager})
	return frappe.get_doc("Donation Project", code)


def make_api_client(name: str, channel: str = "Online Store", active: int = 1, allowed=()):
	existing = frappe.db.get_value("Donation API Client", {"client_name": name})
	if existing:
		client = frappe.get_doc("Donation API Client", existing)
		client.is_active = active
		client.set("allowed_projects", [{"project": p} for p in allowed])
		client.save(ignore_permissions=True)
		return client
	return frappe.get_doc(
		{
			"doctype": "Donation API Client",
			"client_name": name,
			"channel": channel,
			"is_active": active,
			"allowed_projects": [{"project": p} for p in allowed],
		}
	).insert(ignore_permissions=True)


def paid_donation(project: str, amount: float, channel: str = "Website", **extra):
	doc = frappe.get_doc(
		{
			"doctype": "Donation",
			"project": project,
			"amount": amount,
			"channel": channel,
			"status": "Paid",
			**extra,
		}
	)
	doc.flags.from_integration = True
	return doc.insert(ignore_permissions=True)


def iso_ago(hours: float = 1) -> str:
	"""An ISO 8601 timestamp with timezone, `hours` in the past."""
	moment = datetime.now(ZoneInfo(get_system_timezone())) - timedelta(hours=hours)
	return moment.isoformat(timespec="seconds")


def reference(prefix: str = "ORDER") -> str:
	return f"{prefix}-{frappe.generate_hash(length=10)}"
