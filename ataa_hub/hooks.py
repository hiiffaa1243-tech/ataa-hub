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
}
