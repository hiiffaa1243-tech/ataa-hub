"""Fake API demo data for the Postman collection — never real people or keys.

    bench --site <site> execute ataa_hub.setup.demo_api.seed

Creates three projects, four API clients with fixed *local-only* keys (matching
postman/ataa_hub_local.postman_environment.json), one staff user with a key, and the
fundraising event CLOCKTOWER-2026 with terminals T01/T02. Safe to run again.
The full demo seed (donations, users, disbursements) arrives in M9.
"""

import frappe
from frappe.utils import add_days, get_datetime, nowdate

from ataa_hub.constants import FUND_RESTRICTED

IMG = "/assets/ataa_hub/images/projects/"
PROJECTS = [
	# code, title, impact label, units per SAR, target, status, options, image, description
	(
		"SUQYA-01",
		"سقيا ضيوف الرحمن",
		"معتمر سُقي",
		1.0,
		500000,
		"Open",
		[("سقيا 100 معتمر", 100), ("سقيا 250 معتمر", 250), ("سقيا 500 معتمر", 500)],
		IMG + "suqya.webp",
		"مياه باردة لضيوف الرحمن في ساحات الحرم ومحطات القطار، توزَّع يومياً طوال الموسم.",
	),
	(
		"WAFADA-02",
		"مبنى الوفادة",
		"زائر",
		0.1,
		300000,
		"Open",
		[("ضيافة 10 زوار", 150), ("ضيافة 50 زائراً", 700)],
		IMG + "wafada.webp",
		"استقبال ضيوف الرحمن وضيافتهم في مبنى الوفادة: قهوة وتمر وإرشاد بعدة لغات.",
	),
	(
		"IFTAR-03",
		"إفطار صائم",
		"وجبة",
		0.1,
		200000,
		"Open",
		[("إفطار 10 صائمين", 120), ("إفطار 50 صائماً", 600)],
		IMG + "iftar.webp",
		"وجبات إفطار للمعتمرين والصائمين في رمضان وأيام الاثنين والخميس.",
	),
	(
		"MUSHAF-04",
		"أوقف مصحفاً",
		"مصحف",
		0.04,
		150000,
		"Open",
		[("مصحف واحد", 25), ("5 مصاحف", 125), ("10 مصاحف", 250)],
		IMG + "mushaf.webp",
		"مصاحف بترجمات مختلفة تُهدى لضيوف الرحمن، ويبقى أجرها وقفاً جارياً لك.",
	),
	(
		"UMBRELLA-05",
		"مظلة ضيف الرحمن",
		"مظلة",
		0.05,
		100000,
		"Open",
		[("مظلة واحدة", 20), ("10 مظلات", 200)],
		IMG + "umbrella.webp",
		"مظلات تقي ضيوف الرحمن حر الشمس في الطريق إلى الحرم والمشاعر.",
	),
	("WINTER-06", "حقيبة الشتاء (مغلق)", "حقيبة", 0.004, 80000, "Completed", [("حقيبة شتوية", 250)], "", ""),
]

CLIENTS = [
	# client name, channel, active, key, secret, allowed project codes
	("متجر الجمعية الإلكتروني", "Online Store", 1, "demo_store_key", "demo_store_secret", []),
	("أجهزة نقاط البيع — برج الساعة", "POS", 1, "demo_pos_key", "demo_pos_secret", ["SUQYA-01", "WAFADA-02"]),
	("منصة شريكة (موقوفة)", "Partner", 0, "demo_inactive_key", "demo_inactive_secret", []),
]

STAFF_USER = ("staff-api@ataa.test", "demo_staff_key", "demo_staff_secret")
EVENT_CODE = "CLOCKTOWER-2026"


def seed():
	if not (frappe.conf.developer_mode or frappe.conf.allow_tests):
		frappe.throw("Demo keys are for local sites only (developer_mode or allow_tests).")

	projects = {row[0]: _project(*row) for row in PROJECTS}
	clients = {name: _client(name, *rest, projects) for name, *rest in CLIENTS}
	_staff_user()
	_event(projects, clients[CLIENTS[1][0]])
	frappe.db.commit()
	print(f"API demo ready: {len(projects)} projects, {len(clients)} clients, event {EVENT_CODE}.")


def _project(code, title, impact_label, rate, target, status, options, image=None, description=None):
	name = frappe.db.get_value("Project", {"project_code": code})
	doc = frappe.get_doc("Project", name) if name else frappe.new_doc("Project")
	doc.update(
		{
			"project_name": title,
			"project_code": code,
			"company": frappe.db.get_single_value("Ataa Settings", "company"),
			"status": status,
			"is_active": "Yes",
			"fund_type": FUND_RESTRICTED,
			"is_public": 1,
			"public_title": title,
			"public_image": image or None,
			"public_description": description or None,
			"target_amount": target,
			"allow_custom_amount": 1,
			"impact_unit_label": impact_label,
			"impact_units_per_sar": rate,
		}
	)
	doc.set("donation_options", [{"label": label, "amount": amount} for label, amount in options])
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


def _client(name, channel, active, key, secret, allowed_codes, projects):
	existing = frappe.db.get_value("Donation API Client", {"client_name": name})
	doc = (
		frappe.get_doc("Donation API Client", existing) if existing else frappe.new_doc("Donation API Client")
	)
	doc.update({"client_name": name, "channel": channel, "is_active": active})
	doc.set("allowed_projects", [{"project": projects[c]} for c in allowed_codes])
	doc.flags.ignore_permissions = True
	doc.save()
	_set_keys(doc.integration_user, key, secret)
	return doc.name


def _staff_user():
	email, key, secret = STAFF_USER
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Staff API test",
				"send_welcome_email": 0,
				"roles": [{"role": "Donations Accountant"}],
			}
		).insert(ignore_permissions=True)
	_set_keys(email, key, secret)


def _set_keys(user, key, secret):
	doc = frappe.get_doc("User", user)
	doc.api_key, doc.api_secret = key, secret
	doc.flags.ignore_permissions = True
	doc.save()


def _event(projects, pos_client):
	doc = (
		frappe.get_doc("Fundraising Event", EVENT_CODE)
		if frappe.db.exists("Fundraising Event", EVENT_CODE)
		else frappe.new_doc("Fundraising Event")
	)
	doc.update(
		{
			"event_code": EVENT_CODE,
			"event_name": "جناح برج الساعة — مكة المكرمة",
			"location": "برج الساعة، مكة المكرمة",
			"status": "Active",
			"start_datetime": get_datetime(add_days(nowdate(), -7)),
			"end_datetime": get_datetime(add_days(nowdate(), 30)),
			"target_amount": 100000,
			"live_screen_enabled": 1,
		}
	)
	doc.set("projects", [{"project": projects["SUQYA-01"]}, {"project": projects["WAFADA-02"]}])
	doc.set(
		"terminals",
		[
			{"api_client": pos_client, "terminal_id": "T01-CLOCKTOWER", "label": "T01 — المدخل"},
			{"api_client": pos_client, "terminal_id": "T02-CLOCKTOWER", "label": "T02 — الساحة"},
		],
	)
	doc.flags.ignore_permissions = True
	doc.save()
