"""Spending workflows (PRD §7.8, §7.9) and role profiles (§8), written on install and migrate.

They are part of the product, not a user setting, so every migrate makes the
database match this file.
"""

import frappe

from ataa_hub.constants import (
	DSB_WORKFLOW,
	FAL_WORKFLOW,
	ROLE_ACCOUNTANT,
	ROLE_EXECUTIVE,
	ROLE_PROJECT_MANAGER,
	STATE_APPROVED,
	STATE_DRAFT,
	STATE_PAID,
	STATE_PENDING_ACCOUNTANT,
	STATE_PENDING_EXECUTIVE,
	STATE_REJECTED,
)

STYLES = {
	STATE_DRAFT: "Inverse",
	STATE_PENDING_ACCOUNTANT: "Warning",
	STATE_PENDING_EXECUTIVE: "Primary",
	STATE_APPROVED: "Info",
	STATE_REJECTED: "Danger",
	STATE_PAID: "Success",
}

WORKFLOWS = {
	DSB_WORKFLOW: {
		"document_type": "Disbursement Request",
		# (state, docstatus, role allowed to edit while in this state)
		"states": [
			(STATE_DRAFT, 0, ROLE_PROJECT_MANAGER),
			(STATE_PENDING_ACCOUNTANT, 0, ROLE_ACCOUNTANT),
			(STATE_PENDING_EXECUTIVE, 0, ROLE_EXECUTIVE),
			(STATE_APPROVED, 1, ROLE_ACCOUNTANT),
			(STATE_REJECTED, 0, ROLE_EXECUTIVE),
			(STATE_PAID, 1, ROLE_ACCOUNTANT),
		],
		# (from, action, to, role)
		"transitions": [
			(STATE_DRAFT, "Submit for Review", STATE_PENDING_ACCOUNTANT, ROLE_PROJECT_MANAGER),
			(STATE_PENDING_ACCOUNTANT, "Approve", STATE_PENDING_EXECUTIVE, ROLE_ACCOUNTANT),
			(STATE_PENDING_ACCOUNTANT, "Return", STATE_DRAFT, ROLE_ACCOUNTANT),
			(STATE_PENDING_EXECUTIVE, "Approve", STATE_APPROVED, ROLE_EXECUTIVE),
			(STATE_PENDING_EXECUTIVE, "Reject", STATE_REJECTED, ROLE_EXECUTIVE),
			(STATE_APPROVED, "Mark Paid", STATE_PAID, ROLE_ACCOUNTANT),
		],
	},
	FAL_WORKFLOW: {
		"document_type": "Fund Allocation",
		"states": [
			(STATE_DRAFT, 0, ROLE_PROJECT_MANAGER),
			(STATE_DRAFT, 0, ROLE_ACCOUNTANT),
			(STATE_PENDING_EXECUTIVE, 0, ROLE_EXECUTIVE),
			(STATE_APPROVED, 1, ROLE_EXECUTIVE),
			(STATE_REJECTED, 0, ROLE_EXECUTIVE),
		],
		"transitions": [
			(STATE_DRAFT, "Request", STATE_PENDING_EXECUTIVE, ROLE_PROJECT_MANAGER),
			(STATE_DRAFT, "Request", STATE_PENDING_EXECUTIVE, ROLE_ACCOUNTANT),
			(STATE_PENDING_EXECUTIVE, "Approve", STATE_APPROVED, ROLE_EXECUTIVE),
			(STATE_PENDING_EXECUTIVE, "Reject", STATE_REJECTED, ROLE_EXECUTIVE),
		],
	},
}


def setup_workflows():
	for name, spec in WORKFLOWS.items():
		_ensure_masters(spec)
		workflow = (
			frappe.get_doc("Workflow", name)
			if frappe.db.exists("Workflow", name)
			else frappe.new_doc("Workflow")
		)
		workflow.workflow_name = name
		workflow.document_type = spec["document_type"]
		workflow.workflow_state_field = "workflow_state"
		workflow.is_active = 1
		workflow.override_status = 0
		workflow.send_email_alert = 0  # in-app notifications come from the controllers
		workflow.set("states", [])
		workflow.set("transitions", [])
		for state, docstatus, role in spec["states"]:
			workflow.append("states", {"state": state, "doc_status": str(docstatus), "allow_edit": role})
		for state, action, next_state, role in spec["transitions"]:
			workflow.append(
				"transitions",
				{
					"state": state,
					"action": action,
					"next_state": next_state,
					"allowed": role,
					"allow_self_approval": 1,
				},
			)
		workflow.flags.ignore_permissions = True
		workflow.save()


def _ensure_masters(spec):
	for state, *_ in spec["states"]:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": state, "style": STYLES.get(state, "")}
			).insert(ignore_permissions=True)
	for _from, action, *_ in spec["transitions"]:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)


def setup_role_profiles():
	"""Role Profiles pairing our roles with ERPNext's native ones (PRD §8)."""
	from ataa_hub.constants import ROLE_PROFILES

	for name, roles in ROLE_PROFILES.items():
		profile = (
			frappe.get_doc("Role Profile", name)
			if frappe.db.exists("Role Profile", name)
			else frappe.new_doc("Role Profile")
		)
		profile.role_profile = name
		profile.set("roles", [{"role": r} for r in roles if frappe.db.exists("Role", r)])
		profile.flags.ignore_permissions = True
		profile.save()
