"""Shared names used across the app, so they are spelled once."""

# Roles (PRD section 4)
ROLE_EXECUTIVE = "Executive Director"
ROLE_PROJECT_MANAGER = "Project Manager"
ROLE_ACCOUNTANT = "Donations Accountant"
ROLE_API_CLIENT = "Donation API Client"

APP_ROLES = {
	ROLE_EXECUTIVE: {"desk_access": 1},
	ROLE_PROJECT_MANAGER: {"desk_access": 1},
	ROLE_ACCOUNTANT: {"desk_access": 1},
	# Machine users (stores, POS terminals) never log into the desk
	ROLE_API_CLIENT: {"desk_access": 0},
}

# Roles that can see every project (everyone else with "Project Manager" is row-restricted)
FULL_VISIBILITY_ROLES = {"System Manager", "Administrator", ROLE_EXECUTIVE, ROLE_ACCOUNTANT}

# Donation
STATUS_PENDING = "Pending"
STATUS_PAID = "Paid"
STATUS_FAILED = "Failed"
STATUS_REFUNDED = "Refunded"

CHANNEL_WEBSITE = "Website"
CHANNEL_ONLINE_STORE = "Online Store"
CHANNEL_POS = "POS"
CHANNEL_BANK_TRANSFER = "Bank Transfer"
CHANNEL_PARTNER = "Partner"

# Donation Project
PROJECT_ACTIVE = "Active"
PROJECT_COMPLETED = "Completed"

# Disbursement workflow (PRD section 6.5)
WORKFLOW_NAME = "Disbursement Approval"
STATE_DRAFT = "Draft"
STATE_PENDING_ACCOUNTANT = "Pending Accountant Review"
STATE_PENDING_EXECUTIVE = "Pending Executive Approval"
STATE_APPROVED = "Approved"
STATE_REJECTED = "Rejected"
STATE_DISBURSED = "Disbursed"
