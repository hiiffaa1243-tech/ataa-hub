"""Finish the ERPNext setup wizard without a browser (dev containers, CI, tests).

Fake association data only.

    bench --site <site> execute ataa_hub.setup.wizard.complete_setup_wizard
"""

import frappe
from frappe.utils import getdate, nowdate

DEMO_COMPANY = "جمعية عطاء التجريبية"
DEMO_ABBR = "ATA"


def complete_setup_wizard(company_name: str = DEMO_COMPANY, abbr: str = DEMO_ABBR, language: str = "English"):
	if frappe.is_setup_complete():
		return
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	year = getdate(nowdate()).year
	setup_complete(
		{
			"language": language,
			"country": "Saudi Arabia",
			"timezone": "Asia/Riyadh",
			"currency": "SAR",
			"full_name": "Ataa Admin",
			"email": "admin@ataa.test",
			"password": "admin",
			"company_name": company_name,
			"company_abbr": abbr,
			"chart_of_accounts": "Standard",
			"fy_start_date": f"{year}-01-01",
			"fy_end_date": f"{year}-12-31",
		}
	)
	frappe.db.commit()
