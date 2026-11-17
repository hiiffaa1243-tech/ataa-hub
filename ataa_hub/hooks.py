app_name = "ataa_hub"
app_title = "Ataa Hub"
app_publisher = "هيفاء عبدالرزاق"
app_description = "ERPNext app for nonprofits: real-time donations, memberships and governed spending, all in the General Ledger."
app_email = "dev@ataa.test"
app_license = "MIT"

# Installed alongside ERPNext; ERPNext and Frappe core are never modified (PRD §4.1).
required_apps = ["frappe", "erpnext"]

add_to_apps_screen = [
	{
		"name": "ataa_hub",
		"logo": "/assets/ataa_hub/images/ataa-logo.svg",
		"title": "Ataa Hub",
		"route": "/app/project",
	}
]

# ---------------------------------------------------------------------------
# Customizations of native DocTypes ship as fixtures (PRD §5.4).
# Company-specific records (accounts, GENERAL project, tier items/plans,
# modes of payment) are created by ataa_hub.setup.company, because they need
# a Company to exist first.
# ---------------------------------------------------------------------------
fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Ataa Hub"]]},
	{"dt": "Property Setter", "filters": [["module", "=", "Ataa Hub"]]},
	{
		"dt": "Role",
		"filters": [
			[
				"name",
				"in",
				["Executive Director", "Project Manager", "Donations Accountant", "Donation API Client"],
			]
		],
	},
]

# ---------------------------------------------------------------------------
# Install / migrate: idempotent setup (roles' desk access, site defaults,
# company records). Runs again on every migrate so the database matches code.
# ---------------------------------------------------------------------------
after_install = "ataa_hub.setup.install.after_install"
after_migrate = "ataa_hub.setup.install.after_migrate"

# Tests need a finished ERPNext setup with a SAR company.
before_tests = "ataa_hub.setup.install.before_tests"

doc_events = {
	# A company created later (e.g. by the setup wizard) gets our accounts too.
	"Company": {"on_update": "ataa_hub.setup.company.on_company_update"},
	# Project is mandatory on donation/fund accounts; our journals cancel only via their source doc.
	"Journal Entry": {
		"validate": "ataa_hub.overrides.journal_entry.validate",
		"before_cancel": "ataa_hub.overrides.journal_entry.before_cancel",
	},
}

# ---------------------------------------------------------------------------
# Row-level security: a Project Manager only sees the projects they are
# assigned to (Project → Users), and those projects' donations.
# ---------------------------------------------------------------------------
permission_query_conditions = {
	"Project": "ataa_hub.permissions.project_query_conditions",
	"Donation": "ataa_hub.permissions.donation_query_conditions",
}

has_permission = {
	"Project": "ataa_hub.permissions.project_has_permission",
	"Donation": "ataa_hub.permissions.donation_has_permission",
}

# Public donation page is the site's home page
home_page = "donate"
