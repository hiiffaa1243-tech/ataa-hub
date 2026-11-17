app_name = "ataa_hub"
app_title = "Ataa Hub"
app_publisher = "هيفاء عبدالرزاق"
app_description = "Real-time donations hub for nonprofits: any channel, one ledger, governed disbursements."
app_email = "dev@ataa.test"
app_license = "MIT"
required_apps = ["frappe"]

# Shown on the /apps screen after login (Frappe v15+)
add_to_apps_screen = [
	{
		"name": "ataa_hub",
		"logo": "/assets/ataa_hub/images/ataa-logo.svg",
		"title": "Ataa Hub",
		"route": "/app/executive-dashboard",
	}
]

# Public website: the donation page is the site's home page
home_page = "donate"

# ---------------------------------------------------------------------------
# Install / migrate: roles, workflow and defaults are (re)created idempotently
# ---------------------------------------------------------------------------
after_install = "ataa_hub.setup.install.after_install"
after_migrate = "ataa_hub.setup.install.after_migrate"

# ---------------------------------------------------------------------------
# Row-level security: a Project Manager only sees their own projects,
# and the donations / disbursement requests that belong to them.
# ---------------------------------------------------------------------------
permission_query_conditions = {
	"Donation Project": "ataa_hub.permissions.project_query_conditions",
	"Donation": "ataa_hub.permissions.donation_query_conditions",
	"Disbursement Request": "ataa_hub.permissions.disbursement_query_conditions",
}

has_permission = {
	"Donation Project": "ataa_hub.permissions.project_has_permission",
	"Donation": "ataa_hub.permissions.donation_has_permission",
	"Disbursement Request": "ataa_hub.permissions.disbursement_has_permission",
}
