"""Idempotent setup: roles, the disbursement workflow and site defaults.

Runs after `install-app` and after every `migrate`, so the workflow in the
database always matches the code (it is part of the product, not a user setting).
"""

import frappe

from ataa_hub.constants import (
	APP_ROLES,
	ROLE_ACCOUNTANT,
	ROLE_EXECUTIVE,
	ROLE_PROJECT_MANAGER,
	STATE_APPROVED,
	STATE_DISBURSED,
	STATE_DRAFT,
	STATE_PENDING_ACCOUNTANT,
	STATE_PENDING_EXECUTIVE,
	STATE_REJECTED,
	WORKFLOW_NAME,
)

# (state, docstatus, who may edit the document while it is in this state, indicator style)
WORKFLOW_STATES = [
	(STATE_DRAFT, 0, ROLE_PROJECT_MANAGER, "Inverse"),
	(STATE_PENDING_ACCOUNTANT, 0, ROLE_ACCOUNTANT, "Warning"),
	(STATE_PENDING_EXECUTIVE, 0, ROLE_EXECUTIVE, "Primary"),
	(STATE_APPROVED, 1, ROLE_ACCOUNTANT, "Info"),
	(STATE_REJECTED, 0, ROLE_EXECUTIVE, "Danger"),
	(STATE_DISBURSED, 1, ROLE_ACCOUNTANT, "Success"),
]

# (from, action, to, role allowed) — PRD section 6.5
WORKFLOW_TRANSITIONS = [
	(STATE_DRAFT, "Submit for Review", STATE_PENDING_ACCOUNTANT, ROLE_PROJECT_MANAGER),
	(STATE_PENDING_ACCOUNTANT, "Accountant Approve", STATE_PENDING_EXECUTIVE, ROLE_ACCOUNTANT),
	(STATE_PENDING_ACCOUNTANT, "Return", STATE_DRAFT, ROLE_ACCOUNTANT),
	(STATE_PENDING_EXECUTIVE, "Approve", STATE_APPROVED, ROLE_EXECUTIVE),
	(STATE_PENDING_EXECUTIVE, "Reject", STATE_REJECTED, ROLE_EXECUTIVE),
	(STATE_APPROVED, "Confirm Disbursement", STATE_DISBURSED, ROLE_ACCOUNTANT),
]


def after_install():
	setup()
	set_site_defaults()


def after_migrate():
	setup()


def setup():
	create_roles()
	create_disbursement_workflow()
	frappe.db.commit()


def create_roles():
	for role_name, props in APP_ROLES.items():
		if frappe.db.exists("Role", role_name):
			frappe.db.set_value("Role", role_name, props)
		else:
			frappe.get_doc({"doctype": "Role", "role_name": role_name, **props}).insert(
				ignore_permissions=True
			)


def create_disbursement_workflow():
	for state, _docstatus, _role, style in WORKFLOW_STATES:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": state, "style": style}
			).insert(ignore_permissions=True)

	for _from, action, _to, _role in WORKFLOW_TRANSITIONS:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)

	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		workflow = frappe.get_doc("Workflow", WORKFLOW_NAME)
		workflow.states = []
		workflow.transitions = []
	else:
		workflow = frappe.new_doc("Workflow")
		workflow.workflow_name = WORKFLOW_NAME

	workflow.document_type = "Disbursement Request"
	workflow.workflow_state_field = "workflow_state"
	workflow.is_active = 1
	workflow.override_status = 0
	# In-app notifications are sent by the DocType controller; no SMTP needed for the demo.
	workflow.send_email_alert = 0

	for state, docstatus, role, _style in WORKFLOW_STATES:
		workflow.append("states", {"state": state, "doc_status": str(docstatus), "allow_edit": role})

	for from_state, action, to_state, role in WORKFLOW_TRANSITIONS:
		workflow.append(
			"transitions",
			{
				"state": from_state,
				"action": action,
				"next_state": to_state,
				"allowed": role,
				"allow_self_approval": 1,
			},
		)

	workflow.save(ignore_permissions=True)


def set_site_defaults():
	"""Arabic, Riyadh time and SAR — the PRD asks for an Arabic RTL interface."""
	if not frappe.db.exists("Currency", "SAR"):
		frappe.get_doc(
			{
				"doctype": "Currency",
				"currency_name": "SAR",
				"symbol": "ر.س",
				"fraction": "Halala",
				"fraction_units": 100,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	else:
		frappe.db.set_value("Currency", "SAR", "enabled", 1)

	meta = frappe.get_meta("System Settings")
	values = {"language": "ar", "time_zone": "Asia/Riyadh", "currency": "SAR", "float_precision": "2"}
	for field, value in values.items():
		if meta.has_field(field):
			frappe.db.set_single_value("System Settings", field, value)

	frappe.db.set_default("currency", "SAR")
	frappe.db.set_default("time_zone", "Asia/Riyadh")
	frappe.db.set_default("lang", "ar")
	frappe.db.commit()
