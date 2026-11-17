"""Install / migrate / test hooks. Everything here is idempotent.

Roles, custom fields and property setters come from fixtures (synced by Frappe
on install and migrate). This module adds what fixtures can't express:
site defaults and the company-specific records (see setup/company.py).
"""

import frappe

from ataa_hub.setup.company import setup_company
from ataa_hub.setup.wizard import complete_setup_wizard


def after_install():
	set_site_defaults()
	setup_company()


def after_migrate():
	setup_company()


def before_tests():
	"""Tests need a finished ERPNext setup with a SAR company and our records."""
	complete_setup_wizard()
	setup_company()
	frappe.db.commit()


def set_site_defaults():
	"""SAR enabled and Riyadh time. Language is chosen in the setup wizard (Arabic for the demo)."""
	if frappe.db.exists("Currency", "SAR"):
		frappe.db.set_value("Currency", "SAR", "enabled", 1)
	frappe.db.set_default("time_zone", "Asia/Riyadh")
