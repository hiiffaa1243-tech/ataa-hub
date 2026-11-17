"""M1: a fresh install gives the whole foundation, and setup is idempotent (PRD §4.1, §5)."""

import frappe
from frappe.tests import IntegrationTestCase

from ataa_hub.constants import (
	ACCOUNTS,
	APP_ROLES,
	CUSTOMER_GROUP_DONORS,
	FUND_UNRESTRICTED,
	GENERAL_PROJECT_CODE,
	ITEM_GROUP_MEMBERSHIPS,
	MODES_OF_PAYMENT,
	PAID_TIERS,
)
from ataa_hub.setup.company import setup_company
from ataa_hub.tests.factories import company, settings

CUSTOM_FIELDS = {
	"Project": [
		"project_code",
		"fund_type",
		"is_public",
		"target_amount",
		"public_title",
		"public_image",
		"impact_unit_label",
		"impact_units_per_sar",
		"donation_options",
	],
	"Customer": [
		"donor_mobile",
		"membership_tier",
		"membership_status",
		"membership_subscription",
		"member_since",
		"honorary_since",
		"lifetime_giving",
	],
	"Sales Invoice": ["is_membership"],
	"Payment Entry": ["is_membership"],
	"Journal Entry": ["ataa_reference_doctype", "ataa_reference_name"],
}


class TestFoundation(IntegrationTestCase):
	def test_custom_fields_from_fixtures(self):
		for doctype, fields in CUSTOM_FIELDS.items():
			meta = frappe.get_meta(doctype)
			for field in fields:
				self.assertTrue(meta.has_field(field), f"{doctype}.{field} missing")

	def test_roles_from_fixtures(self):
		for role in APP_ROLES:
			self.assertTrue(frappe.db.exists("Role", role), role)
		self.assertEqual(frappe.db.get_value("Role", "Donation API Client", "desk_access"), 0)

	def test_accounts_exist_with_right_root_type(self):
		for account_name, root_type, _type, _hint in ACCOUNTS.values():
			row = frappe.db.get_value(
				"Account",
				{"company": company(), "account_name": account_name},
				["root_type", "is_group"],
				as_dict=True,
			)
			self.assertIsNotNone(row, account_name)
			self.assertEqual((row.root_type, row.is_group), (root_type, 0), account_name)

	def test_modes_of_payment_point_to_company_accounts(self):
		s = settings()
		for name, (_type, _key, settings_field) in MODES_OF_PAYMENT.items():
			self.assertEqual(s.get(settings_field), name)
			account = frappe.db.get_value(
				"Mode of Payment Account", {"parent": name, "company": company()}, "default_account"
			)
			self.assertTrue(account, name)
			self.assertEqual(frappe.db.get_value("Account", account, "company"), company())

	def test_ataa_settings_filled(self):
		s = settings()
		for field in (
			"company",
			"general_project",
			"restricted_income_account",
			"unrestricted_income_account",
			"disbursement_expense_account",
			"fund_transfers_in_account",
			"fund_transfers_out_account",
			"main_bank_account",
		):
			self.assertTrue(s.get(field), field)

	def test_general_project_is_unrestricted(self):
		general = frappe.get_doc("Project", settings().general_project)
		self.assertEqual((general.project_code, general.fund_type), (GENERAL_PROJECT_CODE, FUND_UNRESTRICTED))

	def test_groups(self):
		self.assertTrue(frappe.db.exists("Customer Group", CUSTOMER_GROUP_DONORS))
		self.assertTrue(frappe.db.exists("Item Group", ITEM_GROUP_MEMBERSHIPS))

	def test_each_tier_has_item_and_monthly_plan(self):
		tiers = frappe.get_single("Membership Settings").tiers
		self.assertEqual({t.tier for t in tiers}, set(PAID_TIERS))
		for tier in tiers:
			plan = frappe.get_doc("Subscription Plan", tier.subscription_plan)
			self.assertEqual(plan.item, tier.item)
			self.assertEqual((plan.billing_interval, plan.billing_interval_count), ("Month", 1))
			self.assertEqual(plan.cost, tier.monthly_amount)
			self.assertEqual(frappe.db.get_value("Item", tier.item, "item_group"), ITEM_GROUP_MEMBERSHIPS)

	def test_changing_tier_amount_updates_plan(self):
		ms = frappe.get_single("Membership Settings")
		gold = next(t for t in ms.tiers if t.tier == "Gold")
		gold.monthly_amount = 275
		ms.save()
		self.assertEqual(frappe.db.get_value("Subscription Plan", gold.subscription_plan, "cost"), 275)

	def test_setup_is_idempotent(self):
		counts = lambda: {  # noqa: E731
			dt: frappe.db.count(dt)
			for dt in (
				"Account",
				"Mode of Payment",
				"Mode of Payment Account",
				"Project",
				"Item",
				"Subscription Plan",
			)
		}
		before = counts()
		setup_company()
		setup_company()
		self.assertEqual(counts(), before)

	def test_api_client_projects_link_to_erpnext_project(self):
		field = frappe.get_meta("API Client Project").get_field("project")
		self.assertEqual(field.options, "Project")
