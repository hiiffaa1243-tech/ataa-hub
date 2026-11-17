"""Reconciliation: website donations recorded in Ataa Hub vs paid payments in Moyasar.

Every difference is a row the accountant must look at:
- Missing in Platform : Moyasar took the money but no Paid donation exists (e.g. callback and webhook both failed)
- Missing in Moyasar  : the platform says Paid but Moyasar has no such paid payment
- Amount Mismatch     : both exist with different amounts
- Status Mismatch     : Moyasar paid, but the donation is still Pending / Failed
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, today

from ataa_hub.constants import CHANNEL_WEBSITE, STATUS_PAID
from ataa_hub.payments import PAYMENT_ID_RE, list_paid_payments

MATCHED = "Matched"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = filters.from_date or add_days(today(), -30)
	to_date = filters.to_date or today()

	payments = list_paid_payments(from_date, to_date)

	donations = frappe.get_all(
		"Donation",
		filters=[["channel", "=", CHANNEL_WEBSITE], ["creation", "between", [from_date, to_date]]],
		fields=["name", "amount", "status", "payment_reference", "project"],
	)
	by_payment = {d.payment_reference: d for d in donations if d.payment_reference}
	by_name = {d.name: d for d in donations}

	rows, seen = [], set()
	for p in payments:
		donation = by_payment.get(p.get("id")) or by_name.get((p.get("metadata") or {}).get("donation_id"))
		if not donation:
			# The donation may have been created before the period started.
			donation_id = (p.get("metadata") or {}).get("donation_id")
			if donation_id:
				donation = frappe.db.get_value(
					"Donation",
					donation_id,
					["name", "amount", "status", "payment_reference", "project"],
					as_dict=True,
				)

		moyasar_amount = cint(p.get("amount")) / 100
		if not donation:
			result = "Missing in Platform"
		else:
			seen.add(donation.name)
			if donation.status != STATUS_PAID:
				result = "Status Mismatch"
			elif abs(flt(donation.amount) - moyasar_amount) >= 0.005:
				result = "Amount Mismatch"
			else:
				result = MATCHED

		rows.append(_row(result, p, moyasar_amount, donation))

	for d in donations:
		# Only references shaped like a Moyasar payment id can be reconciled
		# (the fake demo data uses "demo-..." references on purpose).
		is_moyasar = bool(d.payment_reference and PAYMENT_ID_RE.match(d.payment_reference))
		if d.status == STATUS_PAID and d.name not in seen and is_moyasar:
			rows.append(_row("Missing in Moyasar", None, None, d))

	if not filters.show_matched:
		rows = [r for r in rows if r["result"] != MATCHED]

	rows.sort(key=lambda r: r["result"] == MATCHED)
	mismatches = sum(1 for r in rows if r["result"] != MATCHED)
	summary = [
		{"label": _("عمليات ميسّر المدفوعة"), "value": len(payments), "datatype": "Int", "indicator": "Blue"},
		{
			"label": _("تبرعات الصفحة المدفوعة"),
			"value": sum(1 for d in donations if d.status == STATUS_PAID),
			"datatype": "Int",
			"indicator": "Blue",
		},
		{
			"label": _("اختلافات تحتاج مراجعة"),
			"value": mismatches,
			"datatype": "Int",
			"indicator": "Red" if mismatches else "Green",
		},
	]
	return get_columns(), rows, None, None, summary


def _row(result, payment, moyasar_amount, donation):
	return {
		"result": result,
		"result_label": _(result),
		"moyasar_id": payment.get("id") if payment else None,
		"moyasar_amount": moyasar_amount,
		"moyasar_created": (payment.get("created_at") or "")[:19].replace("T", " ") if payment else None,
		"donation": donation.name if donation else None,
		"project": donation.project if donation else None,
		"donation_amount": donation.amount if donation else None,
		"donation_status": _(donation.status) if donation else None,
	}


def get_columns():
	return [
		{"fieldname": "result_label", "label": _("النتيجة"), "fieldtype": "Data", "width": 150},
		{"fieldname": "moyasar_id", "label": _("رقم عملية ميسّر"), "fieldtype": "Data", "width": 290},
		{"fieldname": "moyasar_amount", "label": _("مبلغ ميسّر"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "moyasar_created", "label": _("وقت العملية"), "fieldtype": "Data", "width": 160},
		{
			"fieldname": "donation",
			"label": _("التبرع"),
			"fieldtype": "Link",
			"options": "Donation",
			"width": 150,
		},
		{
			"fieldname": "project",
			"label": _("المشروع"),
			"fieldtype": "Link",
			"options": "Donation Project",
			"width": 110,
		},
		{"fieldname": "donation_amount", "label": _("مبلغ المنصة"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "donation_status", "label": _("حالة التبرع"), "fieldtype": "Data", "width": 110},
		{"fieldname": "result", "label": "code", "fieldtype": "Data", "hidden": 1},
	]
