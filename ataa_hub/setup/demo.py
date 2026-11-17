"""Fake demo data — never real people, phone numbers or keys.

    bench --site ataa.localhost execute ataa_hub.setup.demo.seed

Creates 4 staff users (one per role), 6 projects, ~350 paid donations over the
last 12 months across every channel, disbursement requests in every workflow
state, and 3 API clients with fixed *local-only* keys so the Postman collection
works out of the box.
"""

import random
from datetime import datetime, timedelta

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_months, flt, get_first_day, now_datetime

from ataa_hub.constants import (
	ROLE_ACCOUNTANT,
	ROLE_EXECUTIVE,
	ROLE_PROJECT_MANAGER,
	STATUS_PAID,
	STATUS_PENDING,
)
from ataa_hub.services import update_donor_stats, update_project_totals
from ataa_hub.setup.install import set_site_defaults, setup

DEMO_PASSWORD = "Ataa@Demo2026"  # local demo only

USERS = {
	"ed@ataa.test": ("نورة", "المدير التنفيذي", ROLE_EXECUTIVE),
	"pm@ataa.test": ("خالد", "مدير مشاريع", ROLE_PROJECT_MANAGER),
	"pm2@ataa.test": ("سارة", "مديرة مشاريع", ROLE_PROJECT_MANAGER),
	"accountant@ataa.test": ("عبدالله", "المحاسب", ROLE_ACCOUNTANT),
}

PROJECTS = [
	# code, title, description, target, manager, status, image, options
	(
		"SUQYA-01",
		"سقيا ضيوف الرحمن",
		"توفير مياه الشرب الباردة لضيوف الرحمن في المسجد الحرام وساحاته.",
		500000,
		"pm@ataa.test",
		"Active",
		"suqya",
		[("سقيا 100 معتمر", 100), ("سقيا 250 معتمر", 250), ("سقيا 1000 معتمر", 1000)],
	),
	(
		"WAFADA-02",
		"ضيافة ضيوف الرحمن",
		"وجبات وضيافة للمعتمرين والزوار في المعارض والفعاليات.",
		300000,
		"pm@ataa.test",
		"Active",
		"wafada",
		[("ضيافة 10 زوار", 150), ("ضيافة 50 زائراً", 700)],
	),
	(
		"IFTAR-03",
		"إفطار صائم",
		"وجبات إفطار للصائمين في رمضان قرب الحرم.",
		200000,
		"pm@ataa.test",
		"Active",
		"iftar",
		[("إفطار 10 صائمين", 120), ("إفطار 50 صائماً", 600)],
	),
	(
		"KISWA-04",
		"كسوة العيد للأيتام",
		"كسوة العيد لأبناء الأسر المستفيدة.",
		150000,
		"pm2@ataa.test",
		"Active",
		"kiswa",
		[("كسوة طفل", 300), ("كسوة أسرة", 1200)],
	),
	(
		"TAALEEM-05",
		"منح تعليمية",
		"رسوم دراسية وحقائب مدرسية لطلاب الأسر المستفيدة.",
		400000,
		"pm2@ataa.test",
		"Active",
		"taaleem",
		[("حقيبة مدرسية", 200), ("منحة فصل دراسي", 2500)],
	),
	(
		"WINTER-06",
		"حقيبة الشتاء",
		"مشروع موسمي مغلق — موجود لاختبار رفض التبرع لمشروع غير نشط.",
		80000,
		"pm2@ataa.test",
		"Closed",
		"winter",
		[("حقيبة شتوية", 250)],
	),
]

API_CLIENTS = [
	# name, channel, active, api_key, api_secret, allowed projects
	("متجر الجمعية الإلكتروني", "Online Store", 1, "demo_store_key", "demo_store_secret", []),
	("جهاز معرض الحج 01", "POS", 1, "demo_pos_key", "demo_pos_secret", ["WAFADA-02", "SUQYA-01"]),
	("منصة شريكة (موقوفة)", "Partner", 0, "demo_inactive_key", "demo_inactive_secret", []),
]

FIRST_NAMES = [
	"محمد",
	"فاطمة",
	"عبدالرحمن",
	"نوف",
	"فيصل",
	"ريم",
	"تركي",
	"هند",
	"سلطان",
	"لمى",
	"ماجد",
	"أروى",
]
LAST_NAMES = ["المتبرع", "الخيري", "العطاء", "الإحسان", "البذل"]


def seed(force: bool = False):
	if frappe.db.exists("Donation Project", "SUQYA-01") and not force:
		print("Demo data already exists. Use force=True to add another batch.")
		return

	rng = random.Random(2026)
	setup()
	set_site_defaults()
	complete_setup_wizard()

	create_users()
	create_projects()
	clients = create_api_clients()
	donors = create_donors(rng)
	create_donations(rng, donors, clients)
	create_disbursements()

	frappe.db.commit()
	print_summary()


# ------------------------------------------------------------------ helpers


def complete_setup_wizard():
	"""Skip Frappe's first-login setup wizard: the defaults above already cover it."""
	if frappe.get_meta("System Settings").has_field("setup_complete"):
		frappe.db.set_single_value("System Settings", "setup_complete", 1)
	if frappe.db.has_column("Installed Application", "is_setup_complete"):
		frappe.db.sql("update `tabInstalled Application` set is_setup_complete = 1")
	frappe.db.set_default("desktop:home_page", "workspace")
	frappe.clear_cache()


def create_users():
	for email, (first, last, role) in USERS.items():
		if frappe.db.exists("User", email):
			continue
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first,
				"last_name": last,
				"language": "ar",
				"send_welcome_email": 0,
				"new_password": DEMO_PASSWORD,
				"roles": [{"role": role}],
			}
		)
		user.insert(ignore_permissions=True)


def create_projects():
	for code, title, description, target, manager, _status, image, options in PROJECTS:
		if frappe.db.exists("Donation Project", code):
			continue
		frappe.get_doc(
			{
				"doctype": "Donation Project",
				"project_code": code,
				"title": title,
				"description": description,
				"target_amount": target,
				"project_manager": manager,
				# Create as Active so donations can be recorded; closed ones are closed afterwards.
				"status": "Active",
				"image": f"/assets/ataa_hub/images/projects/{image}.svg",
				"allow_custom_amount": 1,
				"donation_options": [{"label": label, "amount": amount} for label, amount in options],
			}
		).insert(ignore_permissions=True)


def create_api_clients():
	clients = {}
	for name, channel, active, key, secret, allowed in API_CLIENTS:
		existing = frappe.db.get_value("Donation API Client", {"client_name": name})
		if existing:
			clients[channel] = existing
			continue
		client = frappe.get_doc(
			{
				"doctype": "Donation API Client",
				"client_name": name,
				"channel": channel,
				"is_active": active,
				"allowed_projects": [{"project": p} for p in allowed],
			}
		).insert(ignore_permissions=True)

		user = frappe.get_doc("User", client.integration_user)
		user.api_key = key
		user.api_secret = secret
		user.flags.ignore_permissions = True
		user.save()
		clients[channel] = client.name
	return clients


def create_donors(rng):
	donors = []
	for i in range(1, 41):
		mobile = f"+9665000{i:05d}"  # clearly fake range
		name = frappe.db.get_value("Donor", {"mobile": mobile})
		if not name:
			name = (
				frappe.get_doc(
					{
						"doctype": "Donor",
						"full_name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
						"mobile": mobile,
						"email": f"donor{i:03d}@example.com",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		donors.append(name)
	return donors


def _random_moment(rng, months_ago: int) -> datetime:
	start = get_first_day(add_months(now_datetime(), -months_ago))
	moment = datetime.combine(start, datetime.min.time()) + timedelta(
		days=rng.randint(0, 27), hours=rng.randint(8, 22), minutes=rng.randint(0, 59)
	)
	return min(moment, now_datetime() - timedelta(minutes=5))


def create_donations(rng, donors, clients):
	active_codes = [p[0] for p in PROJECTS]
	weights = [30, 18, 16, 14, 14, 8]
	channels = ["Website", "Online Store", "POS", "Bank Transfer"]
	channel_weights = [35, 35, 18, 12]
	amounts = [100, 120, 150, 200, 250, 300, 500, 600, 700, 1000, 1200, 2500, 5000]
	amount_weights = [14, 8, 10, 10, 14, 10, 10, 5, 4, 7, 3, 3, 2]
	pos_projects = ["WAFADA-02", "SUQYA-01"]

	touched_projects, touched_donors = set(), set()

	for i in range(360):
		# More recent months get a little more volume, so the trend line rises
		months_ago = rng.choices(range(12), weights=[16, 14, 12, 11, 10, 9, 8, 7, 6, 5, 5, 4])[0]
		channel = rng.choices(channels, weights=channel_weights)[0]
		project = (
			rng.choice(pos_projects) if channel == "POS" else rng.choices(active_codes, weights=weights)[0]
		)
		amount = rng.choices(amounts, weights=amount_weights)[0]
		paid_on = _random_moment(rng, months_ago)
		donor = rng.choice(donors) if rng.random() < 0.7 else None

		doc = {
			"doctype": "Donation",
			"project": project,
			"amount": amount,
			"channel": channel,
			"status": STATUS_PAID,
			"paid_on": paid_on,
			"donor": donor,
		}
		if channel == "Online Store":
			doc.update(
				api_client=clients["Online Store"],
				external_reference=f"ORDER-{100000 + i}",
				payment_reference=f"pay_demo_{i:05d}",
			)
		elif channel == "POS":
			doc.update(
				api_client=clients["POS"],
				external_reference=f"TXN-T01-{i:06d}",
				payment_reference=f"AUTH-{500000 + i}",
				terminal_id="T01-HAJJ-EXPO",
				card_scheme=rng.choice(["mada", "mada", "visa", "mastercard"]),
				rrn=f"{432118000000 + i}",
			)
		elif channel == "Website":
			doc.update(payment_reference=f"demo-{i:08d}-0000-0000-0000-000000000000")
		else:
			doc.update(
				payment_reference=f"BT-{i:06d}", transfer_proof="/assets/ataa_hub/images/ataa-logo.svg"
			)

		donation = frappe.get_doc(doc)
		donation.flags.from_integration = True
		donation.insert(ignore_permissions=True)
		touched_projects.add(project)
		touched_donors.add(donor)

	# A few bank transfers still waiting for the accountant to verify them
	for i, project in enumerate(["SUQYA-01", "IFTAR-03", "KISWA-04"]):
		frappe.get_doc(
			{
				"doctype": "Donation",
				"project": project,
				"amount": [3000, 1500, 800][i],
				"channel": "Bank Transfer",
				"status": STATUS_PENDING,
				"payment_reference": f"BT-PENDING-{i + 1}",
				"donor_name": "حوالة بانتظار التحقق",
			}
		).insert(ignore_permissions=True)

	for project in touched_projects:
		update_project_totals(project)
	for donor in touched_donors:
		update_donor_stats(donor)

	# Close the seasonal project now that it has history
	for code, _title, _desc, _target, _manager, status, _image, _options in PROJECTS:
		if status != "Active":
			frappe.db.set_value("Donation Project", code, "status", status)


def _as(user, fn, *args):
	previous = frappe.session.user
	frappe.set_user(user)
	try:
		return fn(*args)
	finally:
		frappe.set_user(previous)


def _new_request(project, share, purpose, pm):
	collected = flt(frappe.db.get_value("Donation Project", project, "available_balance"))
	amount = max(round(collected * share, -2), 100)

	def create():
		return frappe.get_doc(
			{"doctype": "Disbursement Request", "project": project, "amount": amount, "purpose": purpose}
		).insert()

	return _as(pm, create)


def _move(doc, steps):
	for user, action in steps:
		doc = _as(user, apply_workflow, doc, action)
	return doc


def create_disbursements():
	if frappe.db.count("Disbursement Request"):
		return
	pm, pm2, acc, ed = "pm@ataa.test", "pm2@ataa.test", "accountant@ataa.test", "ed@ataa.test"
	full = [
		(pm, "Submit for Review"),
		(acc, "Accountant Approve"),
		(ed, "Approve"),
		(acc, "Confirm Disbursement"),
	]

	_move(_new_request("SUQYA-01", 0.35, "شراء 20 ألف عبوة مياه مبردة لموسم العمرة", pm), full)
	_move(
		_new_request("KISWA-04", 0.30, "كسوة 120 طفلاً من الأسر المستفيدة", pm2),
		[(pm2, "Submit for Review")] + full[1:],
	)
	_move(_new_request("SUQYA-01", 0.20, "صيانة برادات المياه في الساحات", pm), full[:3])
	_move(_new_request("IFTAR-03", 0.25, "عقد تموين وجبات العشر الأواخر", pm), full[:2])
	_move(_new_request("WAFADA-02", 0.15, "ضيافة جناح الجمعية في معرض الحج", pm), full[:1])
	_new_request("TAALEEM-05", 0.10, "حقائب مدرسية للفصل الدراسي القادم", pm2)

	rejected = _move(_new_request("WAFADA-02", 0.10, "طباعة مواد دعائية", pm), full[:2])
	rejected.rejection_reason = "ليست من أولويات المشروع في هذا الربع."
	_as(ed, rejected.save)
	_move(rejected, [(ed, "Reject")])


def print_summary():
	print("\nAtaa Hub demo data is ready.\n")
	print(f"  Staff password (all users): {DEMO_PASSWORD}")
	for email, (_first, _last, role) in USERS.items():
		print(f"    {role:<22} {email}")
	print("\n  API keys (local demo only):")
	for _name, channel, active, key, secret, _allowed in API_CLIENTS:
		state = "active" if active else "INACTIVE"
		print(f"    {channel:<13} {state:<9} token {key}:{secret}")
	print()
