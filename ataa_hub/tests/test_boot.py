"""Staff desk boot: one product (عطاء), not ERPNext beside it."""

import frappe
from frappe.tests import IntegrationTestCase

from ataa_hub import boot
from ataa_hub.constants import ROLE_PROFILES
from ataa_hub.tests.factories import make_user

PM = "pm-boot@ataa.test"


def fake_bootinfo():
	return frappe._dict(
		app_data=[
			{"app_name": "erpnext", "on_apps_screen": True},
			{"app_name": "ataa_hub", "on_apps_screen": True},
		],
		home_shell="ERPNext",
		module_sidebars={
			"Ataa Hub": {
				"items": [
					{"label": "Home", "type": "Link", "child": 0},
					{"label": "Members", "type": "Section Break", "child": 0},
					{"label": "Reports", "type": "Section Break", "child": 0},
					{"label": "Ledger", "type": "Link", "child": 1},
					{"label": "Settings", "type": "Section Break", "child": 0},
				]
			}
		},
	)


class TestBoot(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(PM, ROLE_PROFILES["Ataa Project Manager"])

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_staff_see_one_app_and_a_clean_sidebar(self):
		frappe.set_user(PM)
		b = fake_bootinfo()
		boot.extend_bootinfo(b)
		self.assertEqual(b.ataa_staff, 1)
		self.assertEqual(b.home_shell, "Ataa Hub")
		self.assertEqual([a["app_name"] for a in b.app_data if a["on_apps_screen"]], ["ataa_hub"])
		self.assertEqual(
			[i["label"] for i in b.module_sidebars["Ataa Hub"]["items"]], ["Home", "Reports", "Ledger"]
		)

	def test_executive_can_open_the_membership_report(self):
		ed = "ed-boot@ataa.test"
		make_user(ed, ROLE_PROFILES["Ataa Executive Director"])
		self.assertTrue(frappe.has_permission("Customer", "read", user=ed))
		self.assertTrue(frappe.has_permission("Customer", "report", user=ed))
		self.assertFalse(frappe.has_permission("Customer", "write", user=ed))
		frappe.set_user(ed)
		from frappe.desk.query_report import run

		self.assertIn("result", run("Membership Report", filters={}))

	def test_administrator_keeps_the_full_desk(self):
		b = fake_bootinfo()
		boot.extend_bootinfo(b)
		self.assertNotIn("ataa_staff", b)
		self.assertEqual(b.home_shell, "ERPNext")
		self.assertTrue(all(a["on_apps_screen"] for a in b.app_data))
