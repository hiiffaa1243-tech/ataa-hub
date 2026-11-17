"""Monthly impact email to active members (PRD §9.2).

On the 1st of each month every member with status Active gets an Arabic email:
what the association achieved last month (impact units per project, from the
frozen `impact_units` on donations) and their own giving that month.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import add_months, flt, get_first_day, get_last_day, get_url, getdate, nowdate

from ataa_hub.memberships import customer_email


def last_month(today=None):
	start = get_first_day(add_months(getdate(today or nowdate()), -1))
	return start, get_last_day(start)


def association_impact(start, end) -> list[frappe._dict]:
	d = frappe.qb.DocType("Donation")
	rows = (
		frappe.qb.from_(d)
		.select(d.project_title, d.impact_unit_label, Sum(d.impact_units), Sum(d.amount))
		.where((d.docstatus == 1) & (d.posting_date >= start) & (d.posting_date <= end))
		.groupby(d.project, d.project_title, d.impact_unit_label)
		.orderby(Sum(d.amount), order=frappe.qb.desc)
		.run()
	)
	return [frappe._dict(project_title=t, unit=u or "", units=flt(n), amount=flt(a)) for t, u, n, a in rows]


def send_monthly_impact_emails(today=None) -> int:
	start, end = last_month(today)
	impact = association_impact(start, end)
	if not impact:
		return 0
	members = frappe.get_all(
		"Customer", filters={"membership_status": "Active"}, fields=["name", "customer_name"]
	)
	sent = 0
	for member in members:
		email = customer_email(member.name)
		if not email:
			continue
		mine = _member_total(member.name, start, end)
		try:
			frappe.sendmail(
				recipients=[email],
				subject=_("أثر عطائكم في {0}").format(start.strftime("%m/%Y")),
				template="monthly_impact",
				args={
					"customer_name": member.customer_name,
					"month": start.strftime("%m/%Y"),
					"impact": impact[:6],
					"my_total": mine,
					"portal_url": get_url("/my-giving"),
				},
				reference_doctype="Customer",
				reference_name=member.name,
			)
			sent += 1
		except frappe.OutgoingEmailError:
			frappe.clear_last_message()
			break
	return sent


def _member_total(customer, start, end) -> float:
	d = frappe.qb.DocType("Donation")
	donations = (
		frappe.qb.from_(d)
		.select(Sum(d.amount))
		.where(
			(d.donor == customer) & (d.docstatus == 1) & (d.posting_date >= start) & (d.posting_date <= end)
		)
		.run()[0][0]
	)
	pe = frappe.qb.DocType("Payment Entry")
	memberships = (
		frappe.qb.from_(pe)
		.select(Sum(pe.paid_amount))
		.where(
			(pe.party == customer)
			& (pe.is_membership == 1)
			& (pe.docstatus == 1)
			& (pe.posting_date >= start)
			& (pe.posting_date <= end)
		)
		.run()[0][0]
	)
	return flt(donations) + flt(memberships)
