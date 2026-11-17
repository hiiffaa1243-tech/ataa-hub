"""Company-specific setup (PRD §5.2–5.4), idempotent: safe to run on every migrate.

Creates, for the association's company:
- the donation, membership, fund-transfer, expense and clearing accounts,
- Modes of Payment for every channel, pointing at those accounts,
- the Customer Group "Donors" and Item Group "Memberships",
- the GENERAL (unrestricted) Project,
- one Item + monthly Subscription Plan per paid membership tier,
and fills Ataa Settings / Membership Settings where they are still empty.
Nothing that a user already changed is overwritten.
"""

import frappe
from frappe.utils import flt

from ataa_hub.constants import (
	ACC_MAIN_BANK,
	ACC_MEMBERSHIP_INCOME,
	ACC_PROGRAM_EXPENSES,
	ACC_RESTRICTED_INCOME,
	ACC_TRANSFERS_IN,
	ACC_TRANSFERS_OUT,
	ACC_UNRESTRICTED_INCOME,
	ACCOUNTS,
	CUSTOMER_GROUP_DONORS,
	FUND_UNRESTRICTED,
	GENERAL_PROJECT_CODE,
	GENERAL_PROJECT_TITLE,
	ITEM_GROUP_MEMBERSHIPS,
	MODES_OF_PAYMENT,
	PAID_TIERS,
)


def on_company_update(doc, method=None):
	"""doc_event: a company created after install (e.g. by the setup wizard) gets our records.

	Never blocks saving the company: failures are logged and retried on the next migrate.
	"""
	configured = frappe.db.get_single_value("Ataa Settings", "company")
	if configured and configured != doc.name:
		return
	try:
		setup_company(doc.name)
	except Exception:
		frappe.log_error(
			title="Ataa Hub: company setup failed", reference_doctype="Company", reference_name=doc.name
		)


def get_target_company(company=None):
	return (
		company
		or frappe.db.get_single_value("Ataa Settings", "company")
		or frappe.defaults.get_global_default("company")
		or frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	)


def setup_company(company=None) -> bool:
	"""Create everything for `company`. Returns False when there is no company yet."""
	company = get_target_company(company)
	if not company:
		return False

	ensure_groups()
	accounts = ensure_accounts(company)
	modes = ensure_modes_of_payment(company, accounts)
	general = ensure_general_project(company)
	fill_ataa_settings(company, accounts, modes, general)
	fill_membership_settings(accounts)
	sync_membership_tiers()
	return True


# --------------------------------------------------------------------- groups


def _root(doctype, parent_field):
	return frappe.db.get_value(doctype, {"is_group": 1, parent_field: ("in", ("", None))}, "name")


def ensure_groups():
	for doctype, parent_field, name in (
		("Customer Group", "parent_customer_group", CUSTOMER_GROUP_DONORS),
		("Item Group", "parent_item_group", ITEM_GROUP_MEMBERSHIPS),
	):
		if frappe.db.exists(doctype, name):
			continue
		root = _root(doctype, parent_field)
		if not root:  # ERPNext fixtures not installed yet; next migrate retries
			continue
		frappe.get_doc(
			{
				"doctype": doctype,
				frappe.scrub(doctype) + "_name": name,
				parent_field: root,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)


# ------------------------------------------------------------------- accounts


def _parent_account(company, root_type, account_type, hint):
	parent = frappe.db.get_value(
		"Account", {"company": company, "is_group": 1, "account_name": hint, "root_type": root_type}, "name"
	)
	if not parent and account_type == "Bank":
		parent = frappe.db.get_value(
			"Account", {"company": company, "is_group": 1, "account_type": "Bank"}, "name"
		)
	if not parent:
		parent = frappe.db.get_value(
			"Account",
			{"company": company, "is_group": 1, "root_type": root_type, "parent_account": ("in", ("", None))},
			"name",
		)
	return parent


def ensure_accounts(company) -> dict:
	"""Return {key: account name} for every account in constants.ACCOUNTS."""
	result = {}
	for key, (account_name, root_type, account_type, hint) in ACCOUNTS.items():
		existing = frappe.db.get_value(
			"Account", {"company": company, "account_name": account_name, "is_group": 0}, "name"
		)
		if existing:
			result[key] = existing
			continue
		parent = _parent_account(company, root_type, account_type, hint)
		if not parent:
			frappe.throw(f"No {root_type} group account found in company {company}")
		account = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": account_name,
				"parent_account": parent,
				"company": company,
				"account_type": account_type,
				"is_group": 0,
			}
		)
		account.insert(ignore_permissions=True)
		result[key] = account.name
	return result


# ---------------------------------------------------------- modes of payment


def ensure_modes_of_payment(company, accounts) -> dict:
	"""Return {Ataa Settings field: Mode of Payment name}."""
	result = {}
	for name, (mop_type, account_key, settings_field) in MODES_OF_PAYMENT.items():
		if frappe.db.exists("Mode of Payment", name):
			mop = frappe.get_doc("Mode of Payment", name)
		else:
			mop = frappe.get_doc(
				{"doctype": "Mode of Payment", "mode_of_payment": name, "type": mop_type, "enabled": 1}
			)
		needs_save = mop.is_new()
		if not any(row.company == company for row in mop.accounts):
			mop.append("accounts", {"company": company, "default_account": accounts[account_key]})
			needs_save = True
		if needs_save:
			mop.save(ignore_permissions=True)
		result[settings_field] = name
	return result


# ------------------------------------------------------------ general project


def ensure_general_project(company) -> str:
	existing = frappe.db.get_value("Project", {"project_code": GENERAL_PROJECT_CODE}, "name")
	if existing:
		return existing
	project = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": GENERAL_PROJECT_TITLE,
			"project_code": GENERAL_PROJECT_CODE,
			"company": company,
			"status": "Open",
			"is_active": "Yes",
			"fund_type": FUND_UNRESTRICTED,
			"is_public": 1,
			"public_title": GENERAL_PROJECT_TITLE,
			"public_description": "تبرعات عامة تُصرف حيث الحاجة أكبر، بقرار من الإدارة.",
			"allow_custom_amount": 1,
		}
	)
	project.insert(ignore_permissions=True)
	return project.name


# ------------------------------------------------------------------- settings


def _fill(doc, values) -> bool:
	changed = False
	for field, value in values.items():
		if value and not doc.get(field):
			doc.set(field, value)
			changed = True
	return changed


def fill_ataa_settings(company, accounts, modes, general):
	settings = frappe.get_single("Ataa Settings")
	if settings.company and settings.company != company:
		return
	values = {
		"company": company,
		"general_project": general,
		"restricted_income_account": accounts[ACC_RESTRICTED_INCOME],
		"unrestricted_income_account": accounts[ACC_UNRESTRICTED_INCOME],
		"disbursement_expense_account": accounts[ACC_PROGRAM_EXPENSES],
		"fund_transfers_in_account": accounts[ACC_TRANSFERS_IN],
		"fund_transfers_out_account": accounts[ACC_TRANSFERS_OUT],
		"main_bank_account": accounts[ACC_MAIN_BANK],
		**modes,
	}
	if _fill(settings, values):
		settings.flags.ignore_permissions = True
		settings.save()


def fill_membership_settings(accounts):
	settings = frappe.get_single("Membership Settings")
	changed = _fill(settings, {"membership_income_account": accounts[ACC_MEMBERSHIP_INCOME]})
	if not settings.tiers:
		for tier, (amount, label, colour) in PAID_TIERS.items():
			settings.append(
				"tiers", {"tier": tier, "label_ar": label, "monthly_amount": amount, "colour": colour}
			)
		changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.flags.skip_tier_sync = True  # setup_company syncs right after
		settings.save()


# ------------------------------------------------------- membership tiers


def _default_uom():
	return "Nos" if frappe.db.exists("UOM", "Nos") else frappe.db.get_value("UOM", {}, "name")


def sync_membership_tiers():
	"""One Item + monthly Subscription Plan per tier row, kept at the configured amount."""
	company = frappe.db.get_single_value("Ataa Settings", "company")
	if not company or not frappe.db.exists("Item Group", ITEM_GROUP_MEMBERSHIPS):
		return
	currency = frappe.get_cached_value("Company", company, "default_currency")
	income_account = frappe.db.get_single_value("Membership Settings", "membership_income_account")

	for row in frappe.get_all(
		"Membership Tier",
		filters={"parent": "Membership Settings", "parenttype": "Membership Settings"},
		fields=["name", "tier", "label_ar", "monthly_amount", "item", "subscription_plan"],
	):
		item_code = f"MEMBERSHIP-{row.tier.upper()}"
		if not frappe.db.exists("Item", item_code):
			item = frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": item_code,
					"item_name": f"عضوية {row.label_ar or row.tier}",
					"description": f"{row.tier} membership, billed monthly",
					"item_group": ITEM_GROUP_MEMBERSHIPS,
					"stock_uom": _default_uom(),
					"is_stock_item": 0,
					"is_sales_item": 1,
					"is_purchase_item": 0,
					"include_item_in_manufacturing": 0,
					"item_defaults": [{"company": company, "income_account": income_account}]
					if income_account
					else [],
				}
			)
			item.insert(ignore_permissions=True)

		plan_name = f"{row.tier} Monthly"
		if frappe.db.exists("Subscription Plan", plan_name):
			if flt(frappe.db.get_value("Subscription Plan", plan_name, "cost")) != flt(row.monthly_amount):
				plan = frappe.get_doc("Subscription Plan", plan_name)
				plan.cost = row.monthly_amount
				plan.save(ignore_permissions=True)
		else:
			frappe.get_doc(
				{
					"doctype": "Subscription Plan",
					"plan_name": plan_name,
					"item": item_code,
					"currency": currency,
					"price_determination": "Fixed Rate",
					"cost": row.monthly_amount,
					"billing_interval": "Month",
					"billing_interval_count": 1,
				}
			).insert(ignore_permissions=True)

		if row.item != item_code or row.subscription_plan != plan_name:
			frappe.db.set_value(
				"Membership Tier",
				row.name,
				{"item": item_code, "subscription_plan": plan_name},
				update_modified=False,
			)
