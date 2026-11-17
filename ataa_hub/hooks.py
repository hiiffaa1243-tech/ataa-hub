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
	# Workspace number cards (type Custom → ataa_hub.dashboards)
	{"dt": "Number Card", "filters": [["module", "=", "Ataa Hub"]]},
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
		"on_cancel": "ataa_hub.overrides.journal_entry.on_cancel",
	},
	# Event live screen: clear its cache and notify staff views (PRD §7.3)
	"Donation": {
		"on_submit": "ataa_hub.events.on_donation_change",
		"on_cancel": "ataa_hub.events.on_donation_change",
	},
	# Memberships (PRD §7.5, §9.1)
	"Subscription": {"on_update": "ataa_hub.memberships.on_subscription_update"},
	"Sales Invoice": {"validate": "ataa_hub.memberships.on_sales_invoice_validate"},
	"Payment Entry": {
		"validate": "ataa_hub.memberships.on_payment_entry_validate",
		"on_submit": "ataa_hub.memberships.on_payment_entry_change",
		"on_cancel": "ataa_hub.memberships.on_payment_entry_change",
	},
}

# ---------------------------------------------------------------------------
# Jobs (PRD §9.2). Charging runs at 06:00, after ERPNext's own daily
# Subscription job has created the month's invoices.
# ---------------------------------------------------------------------------
scheduler_events = {
	"cron": {
		"0 6 * * *": [
			"ataa_hub.memberships.charge_due_invoices",
			"ataa_hub.memberships.close_ended_memberships",
		],
		"30 6 * * *": [
			"ataa_hub.memberships.resolve_stale_attempts",
			"ataa_hub.reconciliation.run_daily",
		],
	},
	"monthly": [
		"ataa_hub.memberships.evaluate_honorary",
		"ataa_hub.impact.send_monthly_impact_emails",
	],
}

# Executive Director's "grant Honorary" button
doctype_js = {"Customer": "public/js/customer.js"}

# ---------------------------------------------------------------------------
# Row-level security: a Project Manager only sees the projects they are
# assigned to (Project → Users), and those projects' donations.
# ---------------------------------------------------------------------------
permission_query_conditions = {
	"Project": "ataa_hub.permissions.project_query_conditions",
	"Donation": "ataa_hub.permissions.donation_query_conditions",
	"Disbursement Request": "ataa_hub.permissions.disbursement_query_conditions",
	"Fund Allocation": "ataa_hub.permissions.fund_allocation_query_conditions",
	# Portal donors (Website Users) see only their own records (PRD §7.7)
	"Sales Invoice": "ataa_hub.permissions.sales_invoice_query_conditions",
	"Payment Entry": "ataa_hub.permissions.payment_entry_query_conditions",
	"Donor Payment Method": "ataa_hub.permissions.payment_method_query_conditions",
}

has_permission = {
	"Project": "ataa_hub.permissions.project_has_permission",
	"Donation": "ataa_hub.permissions.donation_has_permission",
	"Disbursement Request": "ataa_hub.permissions.disbursement_has_permission",
	"Fund Allocation": "ataa_hub.permissions.fund_allocation_has_permission",
	"Sales Invoice": "ataa_hub.permissions.sales_invoice_has_permission",
	"Payment Entry": "ataa_hub.permissions.payment_entry_has_permission",
	"Donor Payment Method": "ataa_hub.permissions.payment_method_has_permission",
}

# Public donation page is the site's home page
home_page = "donate"

# Pretty public URLs (PRD §7.6, §7.7, §8.2)
website_route_rules = [
	{"from_route": "/gift/<token>", "to_route": "gift"},
	{"from_route": "/verify/<token>", "to_route": "verify"},
	{"from_route": "/event/<event_code>", "to_route": "event"},
	{"from_route": "/my-giving", "to_route": "my_giving"},
	{"from_route": "/my-giving/<section>", "to_route": "my_giving"},
]

# QR codes and links inside Jinja print formats
jinja = {
	"methods": [
		"ataa_hub.utils.qr_data_uri",
		"ataa_hub.ataa_hub.doctype.donation.donation.receipt_verification_url",
		"ataa_hub.ataa_hub.doctype.donation.donation.gift_url",
		"ataa_hub.zatca.zatca_invoice_qr",
	]
}
