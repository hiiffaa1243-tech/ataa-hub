"""Full demo seed (M9): a believable association with fake people and fake money only.

    bench --site <site> execute ataa_hub.setup.demo.seed

Builds on `demo_api.seed` (projects, API clients, the Clock Tower event), then adds:
staff users for every role, fake donors, three months of donations on every
channel (bank, store, POS at the event, gifts), spending requests in every
workflow state, a fund allocation waiting for the Executive Director, and members
in each tier. Card payments are not touched: memberships are marked paid with a
fake reference, so no Moyasar key is needed.

Local sites only. Safe to run again: the donations and spending part runs once.
"""

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from ataa_hub.constants import ROLE_PROFILES
from ataa_hub.donors import get_or_create_donor
from ataa_hub.setup import demo_api

PASSWORD = "Ataa@Demo2026"  # local demo only, printed in the README
MARKER = "DEMO-BANK-001"

STAFF = [
	# email, first name, role profile, project codes (Project Manager only)
	("ed@ataa.test", "المدير التنفيذي", "Ataa Executive Director", []),
	("accountant@ataa.test", "المحاسبة", "Ataa Accountant", []),
	("pm@ataa.test", "مدير مشاريع الحج والعمرة", "Ataa Project Manager", ["SUQYA-01", "WAFADA-02"]),
	("pm2@ataa.test", "مدير مشروع الإفطار", "Ataa Project Manager", ["IFTAR-03"]),
]

# Fake donors: 0500000xxx numbers and .test emails never reach anyone
DONORS = [
	("عبدالله التجريبي", "0500000101", "donor@ataa.test"),
	("سارة الاختبار", "0500000102", "sara@example.test"),
	("محمد النموذج", "0500000103", None),
	("نورة العرض", "0500000104", "noura@example.test"),
	("خالد الوهمي", "0500000105", None),
	("مؤسسة الخير التجريبية", "0500000106", "foundation@example.test"),
]

MEMBERS = [
	# donor index, tier, paid
	(0, "Gold", True),
	(1, "Silver", True),
	(3, "Bronze", True),
	(5, "Gold", False),  # shows up as "Payment Pending"
]


def seed():
	if not (frappe.conf.developer_mode or frappe.conf.allow_tests):
		frappe.throw("Demo data is for local sites only (developer_mode or allow_tests).")

	demo_api.seed()
	projects = {
		code: frappe.db.get_value("Project", {"project_code": code}) for code, *_ in demo_api.PROJECTS
	}
	projects["GENERAL"] = frappe.db.get_single_value("Ataa Settings", "general_project")

	for email, first_name, profile, codes in STAFF:
		_staff(email, first_name, profile)
		for code in codes:
			_assign(projects[code], email)

	donors = [get_or_create_donor(name, mobile, email) for name, mobile, email in DONORS]
	_portal_user(donors[0], DONORS[0][2])

	if frappe.db.exists("Donation", {"payment_reference": MARKER}):
		print("Demo donations already there; staff and donors refreshed.")
	else:
		_donations(projects, donors)
		_spending(projects)
		_memberships(donors)

	frappe.db.commit()
	print(
		f"Demo ready: {frappe.db.count('Donation', {'docstatus': 1})} donations, "
		f"{frappe.db.count('Disbursement Request')} disbursement requests, "
		f"{frappe.db.count('Customer', {'membership_status': ('is', 'set')})} members. "
		f"Log in as ed@ / accountant@ / pm@ / pm2@ataa.test with {PASSWORD}."
	)


# ---------------------------------------------------------------- people


def _staff(email, first_name, profile):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first_name,
				"send_welcome_email": 0,
				"language": "ar",
				"roles": [{"role": r} for r in ROLE_PROFILES[profile]],
			}
		).insert(ignore_permissions=True)
	_set_password(email)


def _set_password(user):
	from frappe.utils.password import update_password

	update_password(user, PASSWORD)


def _assign(project, user):
	doc = frappe.get_doc("Project", project)
	if user not in {row.user for row in doc.users}:
		doc.append("users", {"user": user, "welcome_email_sent": 1})
		doc.flags.ignore_permissions = True
		doc.save()


def _portal_user(customer, email):
	from ataa_hub.memberships import ensure_portal_user

	ensure_portal_user(customer, email)
	_set_password(email)


# ---------------------------------------------------------------- donations


def _donation(project, amount, channel, days_ago=0, submit=True, **extra):
	doc = frappe.get_doc(
		{
			"doctype": "Donation",
			"project": project,
			"amount": amount,
			"channel": channel,
			"posting_date": add_days(nowdate(), -days_ago),
			**extra,
		}
	)
	if channel != "Bank Transfer":
		doc.flags.from_integration = True
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def _donations(projects, donors):
	suqya, wafada, iftar = projects["SUQYA-01"], projects["WAFADA-02"], projects["IFTAR-03"]
	proof = "/files/demo-transfer-proof.pdf"

	# Bank transfers: confirmed ones over three months, two still waiting for the accountant
	bank = [
		(suqya, 5000, 70, donors[5]),
		(wafada, 3000, 45, donors[0]),
		(iftar, 2400, 30, donors[3]),
		(projects["GENERAL"], 10000, 20, donors[5]),
		(suqya, 1500, 5, donors[1]),
	]
	for i, (project, amount, days_ago, donor) in enumerate(bank, start=1):
		_donation(
			project,
			amount,
			"Bank Transfer",
			days_ago,
			donor=donor,
			transfer_proof=proof,
			payment_reference=f"DEMO-BANK-{i:03d}",
		)
	for i, (project, amount) in enumerate(((iftar, 800), (suqya, 1200)), start=len(bank) + 1):
		_donation(
			project,
			amount,
			"Bank Transfer",
			submit=False,
			donor_name=DONORS[4][0],
			donor_mobile=DONORS[4][1],
			transfer_proof=proof,
			payment_reference=f"DEMO-BANK-{i:03d}",
		)

	# Online store orders, spread over three months
	store = demo_api.CLIENTS[0][0]
	store_client = frappe.db.get_value("Donation API Client", {"client_name": store})
	for i, (project, amount, days_ago) in enumerate(
		[
			(suqya, 100, 80),
			(iftar, 120, 60),
			(wafada, 150, 40),
			(suqya, 250, 25),
			(iftar, 240, 10),
			(suqya, 100, 2),
		],
		start=1,
	):
		_donation(
			project,
			amount,
			"Online Store",
			days_ago,
			api_client=store_client,
			external_reference=f"DEMO-ORDER-{i:04d}",
			donor=donors[i % 3],
		)

	# POS at the Clock Tower event during the last few hours (feeds /event/CLOCKTOWER-2026)
	pos = demo_api.CLIENTS[1][0]
	pos_client = frappe.db.get_value("Donation API Client", {"client_name": pos})
	pos_rows = [
		(suqya, 100, "T01-CLOCKTOWER", "mada", 5),
		(wafada, 150, "T02-CLOCKTOWER", "visa", 4.5),
		(suqya, 250, "T01-CLOCKTOWER", "mada", 3),
		(suqya, 50, "T02-CLOCKTOWER", "mastercard", 2),
		(wafada, 300, "T01-CLOCKTOWER", "mada", 1.2),
		(suqya, 100, "T02-CLOCKTOWER", "mada", 0.6),
		(suqya, 500, "T01-CLOCKTOWER", "visa", 0.2),
	]
	for i, (project, amount, terminal, scheme, hours_ago) in enumerate(pos_rows, start=1):
		_donation(
			project,
			amount,
			"POS",
			api_client=pos_client,
			fundraising_event=demo_api.EVENT_CODE,
			terminal_id=terminal,
			card_scheme=scheme,
			rrn=f"DEMO{i:08d}",
			external_reference=f"DEMO-POS-{i:04d}",
			paid_at=add_to_date(now_datetime(), hours=-hours_ago),
		)

	# Gift donations (show on /gift/<token> and in the donor portal)
	for donor, recipient, recipient_email, occasion, show_amount in (
		(donors[0], "أم عبدالله", "mother@example.test", "Eid", 1),
		(donors[1], "صديقتي ريم", "reem@example.test", "Graduation", 0),
	):
		_donation(
			iftar,
			200,
			"Online Store",
			3,
			api_client=store_client,
			external_reference=f"DEMO-GIFT-{frappe.generate_hash(length=6)}",
			donor=donor,
			is_gift=1,
			recipient_name=recipient,
			recipient_email=recipient_email,
			occasion=occasion,
			gift_message="تقبّل الله منكم",
			show_amount_on_gift=show_amount,
		)


# ---------------------------------------------------------------- spending


def _act(doc, action, user):
	frappe.set_user(user)
	try:
		return apply_workflow(doc, action)
	finally:
		frappe.set_user("Administrator")


def _request(project, amount, purpose, user="pm@ataa.test"):
	frappe.set_user(user)
	try:
		return frappe.get_doc(
			{"doctype": "Disbursement Request", "project": project, "amount": amount, "purpose": purpose}
		).insert()
	finally:
		frappe.set_user("Administrator")


def _spending(projects):
	suqya, wafada, iftar = projects["SUQYA-01"], projects["WAFADA-02"], projects["IFTAR-03"]
	pm, acc, ed = "pm@ataa.test", "accountant@ataa.test", "ed@ataa.test"

	paid = _request(suqya, 2000, "شراء 4000 عبوة ماء لضيوف الرحمن")
	for action, user in (("Submit for Review", pm), ("Approve", acc), ("Approve", ed), ("Mark Paid", acc)):
		paid = _act(paid, action, user)

	approved = _request(wafada, 1200, "تمور وقهوة لضيافة الزوار")
	for action, user in (("Submit for Review", pm), ("Approve", acc), ("Approve", ed)):
		approved = _act(approved, action, user)

	waiting_ed = _request(suqya, 1800, "ثلاجات مياه في الساحة الشمالية")
	for action, user in (("Submit for Review", pm), ("Approve", acc)):
		waiting_ed = _act(waiting_ed, action, user)

	waiting_acc = _request(wafada, 600, "أكواب وأدوات ضيافة")
	_act(waiting_acc, "Submit for Review", pm)

	rejected = _request(suqya, 900, "لوحات إعلانية")
	for action, user in (("Submit for Review", pm), ("Approve", acc)):
		rejected = _act(rejected, action, user)
	frappe.set_user(ed)
	try:
		rejected.rejection_reason = "ليست من أغراض المشروع المقيد؛ تُطلب من الصندوق العام."
		rejected.save()
	finally:
		frappe.set_user("Administrator")
	_act(rejected, "Reject", ed)

	_request(iftar, 700, "وجبات إفطار لـ 60 صائماً", user="pm2@ataa.test")  # Draft

	# Fund allocation from the general fund, waiting for the Executive Director
	frappe.set_user(pm)
	try:
		allocation = frappe.get_doc(
			{
				"doctype": "Fund Allocation",
				"from_project": projects["GENERAL"],
				"to_project": wafada,
				"amount": 2500,
				"reason": "زيادة الطلب على الضيافة في نهاية الأسبوع",
			}
		).insert()
	finally:
		frappe.set_user("Administrator")
	_act(allocation, "Request", pm)


# ---------------------------------------------------------------- memberships


def _memberships(donors):
	from ataa_hub import memberships

	for index, tier, paid in MEMBERS:
		customer = donors[index]
		if memberships.has_live_membership(customer):
			continue
		start = add_days(nowdate(), -20)
		subscription = memberships.create_subscription(customer, tier, start_date=start)
		invoice = memberships._first_invoice(subscription)
		if paid:
			memberships.make_payment_entry(invoice, f"demo-membership-{invoice}", posting_date=start)
		else:
			# One declined card charge: the member shows as "Payment Pending" with a retry date
			attempt = frappe.get_doc(
				{
					"doctype": "Membership Charge Attempt",
					"sales_invoice": invoice,
					"customer": customer,
					"attempt_no": 1,
					"status": "Failed",
					"amount": frappe.db.get_value("Sales Invoice", invoice, "grand_total"),
					"error_message": "Insufficient funds (demo)",
					"next_retry_on": add_days(nowdate(), 2),
				}
			)
			attempt.flags.from_charge_job = True
			attempt.insert(ignore_permissions=True)
		memberships.ensure_portal_user(customer, DONORS[index][2])
		memberships.refresh_membership_status(customer)


def summary():
	"""Print what the demo looks like (used to check a fresh demo site)."""
	from ataa_hub import dashboards
	from ataa_hub.accounting import get_project_balance
	from ataa_hub.events import build_event_feed

	print(
		"donations:",
		frappe.db.sql("select channel, docstatus, count(*), sum(amount) from tabDonation group by 1, 2"),
	)
	print(
		"requests:",
		frappe.db.sql("select workflow_state, count(*) from `tabDisbursement Request` group by 1"),
	)
	print(
		"allocations:", frappe.db.sql("select workflow_state, count(*) from `tabFund Allocation` group by 1")
	)
	print(
		"members:",
		frappe.db.sql(
			"select membership_tier, membership_status, count(*) from tabCustomer"
			" where ifnull(membership_status, '') != '' group by 1, 2"
		),
	)
	for code, *_ in demo_api.PROJECTS:
		b = get_project_balance(frappe.db.get_value("Project", {"project_code": code}))
		print(code, "balance", b.balance, "committed", b.committed, "available", b.available)
	feed = build_event_feed(demo_api.EVENT_CODE, now_datetime())
	print("event:", feed["total"], feed["count"], feed["last_hour"])
	for _label, method, _colour in dashboards.CARDS.values():
		print("card", method, getattr(dashboards, method)()["value"])
	paid = frappe.db.get_value("Disbursement Request", {"workflow_state": "Paid"})
	for v in frappe.get_all(
		"Version",
		filters={"ref_doctype": "Disbursement Request", "docname": paid},
		fields=["owner", "creation", "data"],
		order_by="creation asc",
	):
		for field, old, new in frappe.parse_json(v.data).get("changed", []):
			if field == "workflow_state":
				print("audit", paid, v.creation, v.owner, old, "->", new)
