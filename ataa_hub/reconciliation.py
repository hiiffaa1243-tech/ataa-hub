"""Moyasar reconciliation (PRD §9.2, §10).

Moyasar's list of *paid* payments is compared with what we recorded:
website Donations (`payment_reference`) and membership Payment Entries (`reference_no`).

    Matched              both sides agree on the amount
    Missing in ERPNext   Moyasar took the money, we have no record
    Missing at Moyasar   we recorded a payment Moyasar does not list as paid
    Amount Mismatch      both exist, amounts differ
    Cancelled in ERPNext we cancelled it, Moyasar still shows it paid (refund it there)

The daily job also heals the most common gap: a paid website donation whose
callback and webhook were both lost is recorded through the normal verified path.
"""

import json

import frappe
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

MATCHED = "Matched"
MISSING_HERE = "Missing in ERPNext"
MISSING_THERE = "Missing at Moyasar"
AMOUNT_MISMATCH = "Amount Mismatch"
CANCELLED_HERE = "Cancelled in ERPNext"


def list_moyasar_payments(from_date, to_date) -> list[dict]:
	from ataa_hub.payments import list_paid_payments

	return list_paid_payments(from_date, to_date)


def reconcile(from_date, to_date, payments: list[dict] | None = None) -> list[dict]:
	from_date, to_date = getdate(from_date), getdate(to_date)
	if payments is None:
		# One extra day each side: Moyasar dates are UTC, ours are Riyadh time.
		payments = list_moyasar_payments(add_days(from_date, -1), add_days(to_date, 1))
	theirs = {p["id"]: p for p in payments if p.get("status") == "paid"}

	ours = {}
	for row in frappe.get_all(
		"Donation",
		filters={
			"payment_reference": ("is", "set"),
			"channel": "Website",
			"docstatus": ("in", (1, 2)),
			"posting_date": ("between", (add_days(from_date, -1), add_days(to_date, 1))),
		},
		fields=["name", "payment_reference", "amount", "docstatus", "posting_date"],
		order_by="name asc",
	):
		# A cart checkout is one Moyasar payment for several donations: compare the sum.
		seen = ours.get(row.payment_reference)
		if seen:
			doc = seen[1]
			doc.name = f"{doc.name}, {row.name}"
			if row.docstatus == 1:
				doc.amount = flt(doc.amount) + flt(row.amount) if doc.docstatus == 1 else flt(row.amount)
				doc.docstatus = 1
			continue
		ours[row.payment_reference] = ("Donation", row)
	for row in frappe.get_all(
		"Payment Entry",
		filters={
			"is_membership": 1,
			"reference_no": ("is", "set"),
			"docstatus": ("in", (1, 2)),
			"posting_date": ("between", (add_days(from_date, -1), add_days(to_date, 1))),
		},
		fields=["name", "reference_no", "paid_amount as amount", "docstatus", "posting_date"],
	):
		ours[row.reference_no] = ("Payment Entry", row)

	rows = []
	for pid, p in theirs.items():
		created = (p.get("created_at") or "")[:10]
		if created and not (str(from_date) <= created <= str(to_date)):
			continue
		row = {
			"payment_id": pid,
			"created_at": created,
			"moyasar_amount": cint(p.get("amount")) / 100,
			"doctype": None,
			"document": None,
			"our_amount": None,
		}
		match = ours.get(pid)
		if not match:
			row["status"] = MISSING_HERE
		else:
			doctype, doc = match
			row.update(doctype=doctype, document=doc.name, our_amount=flt(doc.amount))
			if doc.docstatus == 2:
				row["status"] = CANCELLED_HERE
			elif round(flt(doc.amount) * 100) != cint(p.get("amount")):
				row["status"] = AMOUNT_MISMATCH
			else:
				row["status"] = MATCHED
		rows.append(row)

	for pid, (doctype, doc) in ours.items():
		if pid in theirs or doc.docstatus != 1 or not (from_date <= getdate(doc.posting_date) <= to_date):
			continue
		rows.append(
			{
				"status": MISSING_THERE,
				"payment_id": pid,
				"created_at": None,
				"moyasar_amount": None,
				"doctype": doctype,
				"document": doc.name,
				"our_amount": flt(doc.amount),
			}
		)
	order = {MISSING_HERE: 0, AMOUNT_MISMATCH: 1, MISSING_THERE: 2, CANCELLED_HERE: 3, MATCHED: 4}
	return sorted(rows, key=lambda r: (order[r["status"]], r["created_at"] or ""))


def run_daily(today=None, payments: list[dict] | None = None) -> dict:
	"""Yesterday and today: heal lost website donations, then store the result for the dashboard."""
	from ataa_hub.ataa_hub.doctype.moyasar_settings.moyasar_settings import get_moyasar_config
	from ataa_hub.payments import verify_and_record_payment

	if payments is None and not get_moyasar_config().secret_key:
		return {}
	end = getdate(today or nowdate())
	start = add_days(end, -1)
	if payments is None:
		payments = list_moyasar_payments(add_days(start, -1), add_days(end, 1))
	by_id = {p["id"]: p for p in payments}

	healed = []
	for row in reconcile(start, end, payments):
		if row["status"] != MISSING_HERE:
			continue
		payment = by_id[row["payment_id"]]
		metadata = payment.get("metadata") or {}
		if metadata.get("donation_id") or metadata.get("donation_ids"):
			try:
				if verify_and_record_payment(row["payment_id"], payment).ok:
					healed.append(row["payment_id"])
			except Exception:
				frappe.log_error(title=f"Reconciliation could not record {row['payment_id']}")

	rows = reconcile(start, end, payments)
	issues = [r for r in rows if r["status"] != MATCHED]
	summary = {
		"from": str(start),
		"to": str(end),
		"checked": len(rows),
		"healed": healed,
		"issues": [{k: r[k] for k in ("status", "payment_id", "document")} for r in issues],
	}
	frappe.db.set_single_value(
		"Moyasar Settings",
		{
			"last_reconciled_on": now_datetime(),
			"reconciliation_issues": len(issues),
			"reconciliation_summary": json.dumps(summary, ensure_ascii=False, indent=1),
		},
	)
	if issues:
		from ataa_hub.constants import ROLE_ACCOUNTANT
		from ataa_hub.spending import users_with_role

		for user in users_with_role(ROLE_ACCOUNTANT):
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"subject": f"مطابقة ميسّر: {len(issues)} عملية تحتاج مراجعة",
					"for_user": user,
					"type": "Alert",
					"document_type": "Moyasar Settings",
					"document_name": "Moyasar Settings",
				}
			).insert(ignore_permissions=True)
	return summary
