"""Donors are ERPNext Customers in the group "Donors" (PRD §4.3, §5.1).

- A returning donor is matched by mobile number (unique `donor_mobile`).
- A Contact is linked to the Customer, so the portal (M6) can find the donor's
  documents from the logged-in user.
- `lifetime_giving` is a cache recomputed from source documents, never incremented.
"""

import re

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from ataa_hub.constants import CUSTOMER_GROUP_DONORS

MOBILE_RE = re.compile(r"^\+9665\d{8}$")


def normalize_mobile(mobile: str | None) -> str | None:
	"""'+966 50 000 0001' -> '+966500000001'. Returns None for empty input."""
	mobile = re.sub(r"[\s-]", "", mobile or "")
	return mobile or None


def is_valid_mobile(mobile: str | None) -> bool:
	return bool(mobile and MOBILE_RE.match(mobile))


def get_or_create_donor(name: str | None, mobile: str | None, email: str | None = None) -> str | None:
	"""Customer name for this donor, creating Customer + Contact the first time.

	Anonymous donations (no mobile) create nothing and return None.
	"""
	mobile = normalize_mobile(mobile)
	if not mobile:
		return None

	existing = frappe.db.get_value("Customer", {"donor_mobile": mobile}, "name")
	if existing:
		if email:
			_add_email_if_missing(existing, email)
		return existing

	display_name = (name or "").strip()[:140] or _("متبرع") + f" {mobile[-4:]}"
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": display_name,
			"customer_type": "Individual",
			"customer_group": CUSTOMER_GROUP_DONORS,
			"territory": _default_territory(),
			"donor_mobile": mobile,
		}
	)
	try:
		customer.insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		# Another request created this donor a moment ago (donor_mobile is unique in the DB).
		frappe.local.message_log = []
		return frappe.db.get_value("Customer", {"donor_mobile": mobile}, "name")

	contact = _create_contact(customer.name, display_name, mobile, email)
	frappe.db.set_value("Customer", customer.name, "customer_primary_contact", contact, update_modified=False)
	return customer.name


def _default_territory():
	return (
		frappe.db.get_single_value("Selling Settings", "territory")
		or frappe.db.get_value("Territory", {"territory_name": "Saudi Arabia"})
		or frappe.db.get_value("Territory", {"is_group": 1, "parent_territory": ("in", ("", None))})
	)


def _create_contact(customer, name, mobile, email):
	contact = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": name,
			"phone_nos": [{"phone": mobile, "is_primary_mobile_no": 1}],
			"email_ids": [{"email_id": email, "is_primary": 1}] if email else [],
			"links": [{"link_doctype": "Customer", "link_name": customer}],
		}
	)
	contact.insert(ignore_permissions=True)
	return contact.name


def _add_email_if_missing(customer, email):
	contact_name = frappe.db.get_value("Customer", customer, "customer_primary_contact")
	if not contact_name:
		return
	contact = frappe.get_doc("Contact", contact_name)
	if any(row.email_id == email for row in contact.email_ids):
		return
	contact.append("email_ids", {"email_id": email, "is_primary": 0 if contact.email_ids else 1})
	contact.save(ignore_permissions=True)


def update_lifetime_giving(customer: str | None) -> None:
	"""Recompute from source documents: submitted donations + the paid part of
	submitted membership invoices. Never incremented, so it can always be rebuilt."""
	if not customer:
		return
	donation = frappe.qb.DocType("Donation")
	donations = (
		frappe.qb.from_(donation)
		.select(Sum(donation.amount))
		.where((donation.donor == customer) & (donation.docstatus == 1))
		.run()[0][0]
	)
	invoice = frappe.qb.DocType("Sales Invoice")
	memberships = (
		frappe.qb.from_(invoice)
		.select(Sum(invoice.grand_total - invoice.outstanding_amount))
		.where((invoice.customer == customer) & (invoice.docstatus == 1) & (invoice.is_membership == 1))
		.run()[0][0]
	)
	frappe.db.set_value(
		"Customer", customer, "lifetime_giving", flt(donations) + flt(memberships), update_modified=False
	)
