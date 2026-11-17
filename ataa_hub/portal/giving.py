"""Donor portal data (PRD §7.7). Everything is read live from source documents,
always filtered by the donor linked to the logged-in user, never by a parameter.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, getdate, nowdate

from ataa_hub import memberships
from ataa_hub.ataa_hub.doctype.donation.donation import gift_url, receipt_verification_url
from ataa_hub.constants import PAID_TIERS, TIER_HONORARY

RECEIPT_FORMAT = "Ataa Donation Receipt"
GIFT_FORMAT = "Ataa Gift Card"
HONORARY_LABEL, HONORARY_COLOUR = "شرفي", "#1F6F5C"


# ================================================================ who is asking


def customers_for_user(user: str | None = None) -> list[str]:
	"""Every Customer linked to the user's Contact(s)."""
	user = user or frappe.session.user
	if user == "Guest":
		return []
	contact = frappe.qb.DocType("Contact")
	link = frappe.qb.DocType("Dynamic Link")
	return (
		frappe.qb.from_(link)
		.join(contact)
		.on(contact.name == link.parent)
		.select(link.link_name)
		.distinct()
		.where((link.parenttype == "Contact") & (link.link_doctype == "Customer") & (contact.user == user))
		.run(pluck=True)
	)


def require_donor() -> str:
	"""Portal pages: Guests go to the login page, staff without a donor record get 403."""
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + (
			frappe.request.path if frappe.request else "/my-giving"
		)
		raise frappe.Redirect
	customers = customers_for_user()
	if not customers:
		frappe.throw(_("لا يوجد سجل متبرع مرتبط بهذا الحساب."), frappe.PermissionError)
	return customers[0]


# ================================================================ membership card


def membership_card(customer: str) -> frappe._dict | None:
	c = frappe.db.get_value(
		"Customer",
		customer,
		["membership_tier", "membership_status", "member_since", "honorary_since", "membership_subscription"],
		as_dict=True,
	)
	if not c or not c.membership_tier:
		return None

	card = frappe._dict(
		tier=c.membership_tier,
		status=c.membership_status,
		member_since=c.member_since,
		honorary=c.membership_tier == TIER_HONORARY,
		honorary_since=c.honorary_since,
	)
	if card.honorary:
		card.label, card.colour = HONORARY_LABEL, HONORARY_COLOUR
		return card  # Honorary: no billing fields (PRD §7.7.1)

	row = memberships.tier_row(c.membership_tier)
	card.label = (row.label_ar if row else None) or PAID_TIERS.get(
		c.membership_tier, ("", c.membership_tier)
	)[1]
	card.colour = (row.colour if row else None) or "#AD8F52"
	card.monthly_amount = flt(row.monthly_amount) if row else None

	last = frappe.get_all(
		"Payment Entry",
		filters={"party_type": "Customer", "party": customer, "is_membership": 1, "docstatus": 1},
		fields=["posting_date", "paid_amount"],
		order_by="posting_date desc, creation desc",
		limit=1,
	)
	card.last_charge = last[0] if last else None

	sub = (
		frappe.db.get_value(
			"Subscription", c.membership_subscription, ["status", "current_invoice_start"], as_dict=True
		)
		if c.membership_subscription
		else None
	)
	card.live = bool(sub and sub.status not in ("Cancelled", "Completed"))
	card.ends_on = None if card.live or not sub else sub.current_invoice_start
	open_invoices = memberships.open_membership_invoices(customer)
	if open_invoices:
		retry = frappe.get_all(
			"Membership Charge Attempt",
			filters={"sales_invoice": open_invoices[0], "status": "Failed"},
			pluck="next_retry_on",
			order_by="attempt_no desc",
			limit=1,
		)
		card.next_charge = (retry[0] if retry else None) or frappe.db.get_value(
			"Sales Invoice", open_invoices[0], "due_date"
		)
	else:
		card.next_charge = sub.current_invoice_start if card.live else None

	method = frappe.db.get_value(
		"Donor Payment Method",
		{"customer": customer, "status": "Active"},
		["title", "expiry_month", "expiry_year"],
		order_by="is_default desc, creation desc",
		as_dict=True,
	)
	card.payment_method = method.title if method else None
	card.tiers = [
		frappe._dict(tier=r.tier, label=r.label_ar or r.tier, amount=flt(r.monthly_amount))
		for r in memberships.settings().tiers
		if r.subscription_plan and r.tier != c.membership_tier
	]
	return card


# ================================================================ donations


DONATION_FIELDS = [
	"name",
	"posting_date",
	"project",
	"project_title",
	"amount",
	"channel",
	"impact_units",
	"impact_unit_label",
	"is_gift",
	"recipient_name",
	"occasion",
	"gift_token",
	"receipt_token",
	"docstatus",
]


def donations(customer, from_date=None, to_date=None, project=None, channel=None, limit=None):
	filters = {"donor": customer, "docstatus": ("in", (1, 2))}
	if from_date and to_date:
		filters["posting_date"] = ("between", (getdate(from_date), getdate(to_date)))
	elif from_date:
		filters["posting_date"] = (">=", getdate(from_date))
	elif to_date:
		filters["posting_date"] = ("<=", getdate(to_date))
	if project:
		filters["project"] = project
	if channel:
		filters["channel"] = channel
	rows = frappe.get_all(
		"Donation",
		filters=filters,
		fields=DONATION_FIELDS,
		order_by="posting_date desc, creation desc",
		limit=limit or 0,
	)
	for row in rows:
		row.cancelled = row.docstatus == 2
		row.verify_url = receipt_verification_url(row.receipt_token)
		row.gift_url = gift_url(row.gift_token) if row.is_gift else None
	return rows


def impact_by_project(customer) -> list[frappe._dict]:
	donation = frappe.qb.DocType("Donation")
	return [
		frappe._dict(project_title=r[0], amount=flt(r[1]), impact_units=flt(r[2]), impact_unit_label=r[3])
		for r in (
			frappe.qb.from_(donation)
			.select(
				donation.project_title,
				Sum(donation.amount),
				Sum(donation.impact_units),
				donation.impact_unit_label,
			)
			.where((donation.donor == customer) & (donation.docstatus == 1))
			.groupby(donation.project, donation.project_title, donation.impact_unit_label)
			.orderby(Sum(donation.amount), order=frappe.qb.desc)
			.run()
		)
	]


def gifts(customer):
	return [row for row in donations(customer) if row.is_gift and not row.cancelled]


def donor_projects(customer):
	return frappe.get_all(
		"Donation",
		filters={"donor": customer, "docstatus": 1},
		fields=["project", "project_title"],
		distinct=True,
		order_by="project_title asc",
	)


# ================================================================ annual statement


def statement(customer, year) -> frappe._dict:
	year = cint(year) or getdate(nowdate()).year
	start, end = f"{year}-01-01", f"{year}-12-31"
	donation_rows = [r for r in donations(customer, start, end) if not r.cancelled]
	membership_rows = frappe.get_all(
		"Payment Entry",
		filters={
			"party_type": "Customer",
			"party": customer,
			"is_membership": 1,
			"docstatus": 1,
			"posting_date": ("between", (start, end)),
		},
		fields=["name", "posting_date", "paid_amount"],
		order_by="posting_date asc",
	)
	total_donations = sum(flt(r.amount) for r in donation_rows)
	total_memberships = sum(flt(r.paid_amount) for r in membership_rows)
	return frappe._dict(
		year=year,
		customer=customer,
		customer_name=frappe.db.get_value("Customer", customer, "customer_name"),
		donations=sorted(donation_rows, key=lambda r: (r.posting_date, r.name)),
		memberships=membership_rows,
		total_donations=total_donations,
		total_memberships=total_memberships,
		total=total_donations + total_memberships,
		company=frappe.db.get_single_value("Ataa Settings", "company"),
		generated_on=nowdate(),
	)


def statement_years(customer) -> list[int]:
	years = {
		getdate(d).year
		for d in frappe.get_all("Donation", {"donor": customer, "docstatus": 1}, pluck="posting_date")
	}
	years |= {
		getdate(d).year
		for d in frappe.get_all(
			"Payment Entry", {"party": customer, "is_membership": 1, "docstatus": 1}, pluck="posting_date"
		)
	}
	years.add(getdate(nowdate()).year)
	return sorted(years, reverse=True)


# ================================================================ PDF downloads


def _own_donation(name) -> frappe._dict:
	customers = customers_for_user()
	row = frappe.db.get_value("Donation", name, ["name", "donor", "docstatus", "is_gift"], as_dict=True)
	if not row or row.donor not in customers or row.docstatus != 1:
		frappe.throw(_("هذا الإيصال غير متاح."), frappe.PermissionError)
	return row


def _send_pdf(filename, pdf):
	frappe.local.response.filename = filename
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "pdf"


@frappe.whitelist()
def download_receipt(name: str):
	_own_donation(name)
	_send_pdf(f"receipt-{name}.pdf", render_print(name, RECEIPT_FORMAT, as_pdf=True))


@frappe.whitelist()
def download_gift_card(name: str):
	if not _own_donation(name).is_gift:
		frappe.throw(_("هذا التبرع ليس إهداءً."), frappe.PermissionError)
	_send_pdf(f"gift-{name}.pdf", render_print(name, GIFT_FORMAT, as_pdf=True))


@frappe.whitelist()
def download_statement(year: int | str | None = None):
	customer = require_donor()
	data = statement(customer, year)
	_send_pdf(f"statement-{data.year}.pdf", render_statement(data, as_pdf=True))


def render_print(name, print_format, as_pdf=False):
	"""The caller has already checked that the donor owns the document."""
	frappe.flags.ignore_print_permissions = True
	try:
		return frappe.get_print(
			"Donation", name, print_format, as_pdf=as_pdf, no_letterhead=1, pdf_generator="wkhtmltopdf"
		)
	finally:
		frappe.flags.ignore_print_permissions = False


def render_statement(data, as_pdf=False):
	from frappe.utils.pdf import get_pdf

	html = frappe.render_template("ataa_hub/templates/print/annual_statement.html", {"s": data})
	return get_pdf(html) if as_pdf else html
