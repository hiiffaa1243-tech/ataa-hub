"""M0 spike checks, run with `bench --site <site> execute spike_checks.<fn>`.

Throwaway code: answers questions, is not part of the ataa_hub app.
Every finding is printed as a line starting with "SPIKE:" so spike.sh can collect it.
"""

import inspect
import os

import frappe
from frappe.utils import add_months, getdate, nowdate

COMPANY = "Ataa Spike"


def say(msg):
	print(f"SPIKE: {msg}", flush=True)


def ensure_setup():
	"""Run the ERPNext setup wizard headless (company, chart of accounts, fiscal year)."""
	if frappe.db.exists("Company", COMPANY):
		return
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	year = getdate(nowdate()).year
	setup_complete(
		{
			"language": "English",
			"country": "Saudi Arabia",
			"timezone": "Asia/Riyadh",
			"currency": "SAR",
			"full_name": "Spike Admin",
			"email": "admin@spike.test",
			"password": "admin",
			"company_name": COMPANY,
			"company_abbr": "ATS",
			"chart_of_accounts": "Standard",
			"fy_start_date": f"{year}-01-01",
			"fy_end_date": f"{year}-12-31",
		}
	)
	frappe.db.commit()


def _invoices(sub_name):
	return frappe.get_all(
		"Sales Invoice",
		filters={"subscription": sub_name},
		fields=["name", "docstatus", "posting_date", "due_date", "from_date", "to_date", "grand_total"],
	)


def subscription_timing():
	ensure_setup()
	versions = {app: frappe.get_attr(f"{app}.__version__") for app in ("frappe", "erpnext")}
	say(f"Versions: {versions}")

	if not frappe.db.exists("Item", "SPIKE-GOLD"):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "SPIKE-GOLD",
				"item_name": "Gold Membership (spike)",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"is_stock_item": 0,
				"stock_uom": "Nos",
			}
		).insert()
	if not frappe.db.exists("Subscription Plan", "SPIKE-GOLD-MONTHLY"):
		frappe.get_doc(
			{
				"doctype": "Subscription Plan",
				"plan_name": "SPIKE-GOLD-MONTHLY",
				"item": "SPIKE-GOLD",
				"price_determination": "Fixed Rate",
				"cost": 250,
				"currency": "SAR",
				"billing_interval": "Month",
				"billing_interval_count": 1,
			}
		).insert()
	customer = frappe.db.get_value("Customer", {"customer_name": "Spike Donor"}) or (
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "Spike Donor",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			}
		)
		.insert()
		.name
	)

	sub = frappe.get_doc(
		{
			"doctype": "Subscription",
			"party_type": "Customer",
			"party": customer,
			"company": COMPANY,
			"start_date": nowdate(),
			"generate_invoice_at": "Beginning of the current subscription period",
			"submit_invoice": 1,
			"plans": [{"plan": "SPIKE-GOLD-MONTHLY", "qty": 1}],
		}
	)
	sub.insert()
	frappe.db.commit()
	say(
		f"Subscription fields available: {sorted(f.fieldname for f in sub.meta.fields if f.fieldtype not in ('Section Break', 'Column Break', 'Tab Break'))}"
	)
	say(
		f"After insert: status={sub.status}, period={sub.current_invoice_start}..{sub.current_invoice_end}, invoices={_invoices(sub.name)}"
	)

	say(f"Subscription.process signature: {inspect.signature(sub.process)}")
	sub.reload()
	sub.process()
	frappe.db.commit()
	sub.reload()
	say(f"After process() today: status={sub.status}, invoices={_invoices(sub.name)}")

	# Simulate next month: does a second invoice appear, and is it due at period start?
	next_month = add_months(nowdate(), 1)
	params = inspect.signature(sub.process).parameters
	try:
		if "posting_date" in params:
			sub.process(posting_date=next_month)
		else:
			frappe.flags.current_date = next_month
			sub.process()
		frappe.db.commit()
		sub.reload()
		say(f"After process() at {next_month}: status={sub.status}, invoices={_invoices(sub.name)}")
	finally:
		frappe.flags.current_date = None

	hooks = frappe.get_hooks("scheduler_events")
	jobs = [
		j
		for group in hooks.values()
		for j in (group if isinstance(group, list) else [x for v in group.values() for x in v])
	]
	say(f"Native subscription scheduler jobs: {[j for j in jobs if 'subscription' in j.lower()]}")


def publish_test_event():
	ensure_setup()
	for room in ("website", "all"):
		frappe.publish_realtime(f"ataa_spike_{room}", {"room": room}, room=room)
	frappe.publish_realtime("ataa_spike_broadcast", {"room": None})
	frappe.db.commit()
	say("Published ataa_spike_website, ataa_spike_all, ataa_spike_broadcast")


def moyasar_token_charge():
	"""Create a token with Moyasar's public test card, then charge it with 3ds:false.

	Test keys only, read from the environment, never stored.
	"""
	import requests

	pk, sk = os.environ.get("MOYASAR_PUBLISHABLE_KEY"), os.environ.get("MOYASAR_SECRET_KEY")
	if not (pk and sk) or not (pk.startswith("pk_test_") and sk.startswith("sk_test_")):
		say("Moyasar: need MOYASAR_PUBLISHABLE_KEY=pk_test_… and MOYASAR_SECRET_KEY=sk_test_…")
		raise SystemExit(1)

	token = requests.post(
		"https://api.moyasar.com/v1/tokens",
		auth=(pk, ""),
		json={
			"name": "Spike Tester",
			"number": "4111111111111111",  # Moyasar published test card
			"month": "12",
			"year": str(getdate(nowdate()).year + 2),
			"cvc": "123",
			"save_only": True,
			"callback_url": "https://example.test/callback",
		},
		timeout=30,
	).json()
	say(
		f"Token create: status={token.get('status')} brand={token.get('brand')} last4={token.get('last_four')} needs_3ds={bool(token.get('verification_url'))}"
	)
	if token.get("status") != "active":
		say("Token not active without 3DS: the real sign-up must complete 3DS in the browser (expected).")
		return

	payment = requests.post(
		"https://api.moyasar.com/v1/payments",
		auth=(sk, ""),
		json={
			"amount": 25000,
			"currency": "SAR",
			"description": "Spike membership charge",
			"source": {"type": "token", "token": token["id"], "3ds": False},
			"metadata": {"spike": "m0"},
		},
		timeout=30,
	).json()
	fetched = requests.get(
		f"https://api.moyasar.com/v1/payments/{payment.get('id')}", auth=(sk, ""), timeout=30
	).json()
	say(
		f"Token charge (3ds:false): create status={payment.get('status')}, fetched status={fetched.get('status')}, message={fetched.get('source', {}).get('message')}"
	)
