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
	(0, "Aoun", True),
	(1, "Adeed", True),
	(3, "Muazir", True),
	(5, "Kareem", False),  # shows up as "Payment Pending"
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

	_bank_accounts()
	donors = [get_or_create_donor(name, mobile, email) for name, mobile, email in DONORS]
	_portal_user(donors[0], DONORS[0][2])

	if frappe.db.exists("Donation", {"payment_reference": MARKER}):
		print("Demo donations already there; staff and donors refreshed.")
	else:
		_donations(projects, donors)
		_spending(projects)
		_memberships(donors)
	if not frappe.db.count("Custody"):
		_custody(projects)
	for c in frappe.get_all("Custody", filters={"holder_name": ("is", "not set")}, fields=["name", "holder"]):
		frappe.db.set_value("Custody", c.name, "holder_name", frappe.utils.get_fullname(c.holder))

	frappe.db.commit()
	print(
		f"Demo ready: {frappe.db.count('Donation', {'docstatus': 1})} donations, "
		f"{frappe.db.count('Disbursement Request')} disbursement requests, "
		f"{frappe.db.count('Customer', {'membership_status': ('is', 'set')})} members. "
		f"Log in as ed@ / accountant@ / pm@ / pm2@ataa.test with {PASSWORD}."
	)


# ------------------------------------------------------------ bank accounts

# Fake IBANs (valid checksum so ERPNext accepts them; the accounts do not exist): shown on the checkout page
# for the "bank transfer" option.
BANK_ACCOUNTS = [
	("مصرف الراجحي", "حساب التبرعات العامة", "SA7380000000608010000001"),
	("البنك الأهلي السعودي", "حساب المشاريع", "SA7910000000000000000002"),
	("بنك البلاد", "حساب الأوقاف", "SA6515000000000000000003"),
]


def _bank_accounts():
	company = frappe.db.get_single_value("Ataa Settings", "company")
	gl = frappe.db.get_single_value("Ataa Settings", "main_bank_account")
	for i, (bank, account_name, iban) in enumerate(BANK_ACCOUNTS):
		if not frappe.db.exists("Bank", bank):
			frappe.get_doc({"doctype": "Bank", "bank_name": bank}).insert(ignore_permissions=True)
		if frappe.db.exists("Bank Account", {"iban": iban}):
			continue
		frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": account_name,
				"bank": bank,
				"company": company,
				"account": gl if i == 0 else _bank_gl(company, gl, bank),
				"is_company_account": 1,
				"is_default": int(i == 0),
				"iban": iban,
				"bank_account_no": iban[-10:],
			}
		).insert(ignore_permissions=True)


def _bank_gl(company, main_gl, bank):
	"""ERPNext allows one Bank Account per ledger account: one Bank-type account per bank."""
	existing = frappe.db.get_value("Account", {"company": company, "account_name": bank, "is_group": 0})
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": bank,
				"parent_account": frappe.db.get_value("Account", main_gl, "parent_account"),
				"company": company,
				"account_type": "Bank",
				"is_group": 0,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


# ---------------------------------------------------------------- people


def _staff(email, first_name, profile):
	_staff_user(email, first_name, profile)
	# Land on the staff dashboard (the app's route, /desk/ataa-home), not ERPNext's home.
	# A default workspace would win over the app, so it is cleared.
	frappe.db.set_value(
		"User", email, {"default_workspace": None, "default_app": "ataa_hub"}, update_modified=False
	)


def _staff_user(email, first_name, profile):
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


# ---------------------------------------------------------------- custody (عهد)


def _invoice_image(number: int, supplier: str, amount: float) -> str:
	"""A fake receipt picture, so the closing report has invoices to show."""
	import io

	from PIL import Image, ImageDraw

	img = Image.new("RGB", (420, 300), "white")
	d = ImageDraw.Draw(img)
	d.rectangle([8, 8, 411, 291], outline="#AD8F52", width=4)
	for y, text in enumerate(
		(
			f"DEMO INVOICE #{number}",
			f"Supplier ref. S-{number % 7 + 1:03d}",
			"VAT No. 300000000000003",
			f"TOTAL: {amount:,.2f} SAR",
			"FAKE DATA",
		)
	):
		d.text((30, 40 + y * 45), text, fill="#1f1d1a")
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	f = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"demo-invoice-{number}.png",
			"content": buf.getvalue(),
			"is_private": 1,
		}
	).insert(ignore_permissions=True)
	return f.file_url


def _custody(projects):
	from ataa_hub import custody

	pm, acc = "pm@ataa.test", "accountant@ataa.test"

	def new(project, amount, purpose, user=pm):
		frappe.set_user(user)
		try:
			return (
				frappe.get_doc(
					{"doctype": "Custody", "project": project, "amount": amount, "purpose": purpose}
				)
				.insert()
				.name
			)
		finally:
			frappe.set_user("Administrator")

	def as_acc(fn, name, *args):
		frappe.set_user(acc)
		try:
			fn(name, *args)
		finally:
			frappe.set_user("Administrator")

	def buy(name, rows, user=pm):
		frappe.set_user(user)
		try:
			doc = frappe.get_doc("Custody", name)
			for i, (desc, supplier, amount) in enumerate(rows):
				n = 1000 + frappe.db.count("File", {"file_name": ("like", "demo-invoice-%")}) + i
				doc.append(
					"expenses",
					{
						"description": desc,
						"supplier_name": supplier,
						"amount": amount,
						"invoice": _invoice_image(n, supplier, amount),
					},
				)
			doc.save()
		finally:
			frappe.set_user("Administrator")

	suqya, wafada = projects["SUQYA-01"], projects["WAFADA-02"]

	# Closed with a report
	closed = new(suqya, 1500, "مشتريات توزيع الماء في الساحات")
	as_acc(custody.approve_and_pay, closed)
	buy(
		closed,
		[
			("ثلاجات ماء متنقلة", "مؤسسة البرودة", 640),
			("أكواب ورقية", "تموينات الحرم", 210.5),
			("نقل وتحميل", "نقليات مكة", 300),
		],
	)
	as_acc(custody.close, closed)

	# Open, partly spent
	open_ = new(wafada, 2000, "ضيافة الوفود هذا الأسبوع")
	as_acc(custody.approve_and_pay, open_)
	buy(open_, [("تمر سكري 20 كرتون", "تمور القصيم", 780), ("قهوة وهيل", "محمصة الديرة", 245)])

	# Spent in full: waiting for the accountant to close it
	full = new(suqya, 600, "مظلات وتبريد لنقطة السقيا")
	as_acc(custody.approve_and_pay, full)
	buy(full, [("مراوح رذاذ", "عالم التبريد", 450), ("أسلاك وتوصيلات", "عدد الحرم", 150)])

	# New request
	new(wafada, 900, "مستلزمات استقبال الزوار يوم الجمعة")


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
