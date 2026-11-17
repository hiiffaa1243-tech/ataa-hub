"""Business logic shared by DocTypes, the public API and the donation page.

Totals are always *recomputed from the source rows* (SUM over donations and
disbursements) instead of being incremented. Recomputing gives the same result
however many times it runs, so a retry, a refund or a late webhook can never
leave the project balance out of sync.
"""

import frappe
from frappe import _
from frappe.utils import flt

from ataa_hub.constants import (
	STATE_APPROVED,
	STATE_DISBURSED,
	STATUS_PAID,
)

# ------------------------------------------------------------------ projects


def _sum_paid_donations(project: str) -> float:
	return flt(
		frappe.db.sql(
			"""select coalesce(sum(amount), 0) from `tabDonation`
			where project = %s and status = %s""",
			(project, STATUS_PAID),
		)[0][0]
	)


def _sum_disbursements(project: str, state: str, exclude: str | None = None) -> float:
	return flt(
		frappe.db.sql(
			"""select coalesce(sum(amount), 0) from `tabDisbursement Request`
			where project = %s and docstatus = 1 and workflow_state = %s and name != %s""",
			(project, state, exclude or ""),
		)[0][0]
	)


def update_project_totals(project: str | None) -> None:
	"""Recompute collected / disbursed / available / progress for one project."""
	if not project or not frappe.db.exists("Donation Project", project):
		return

	collected = _sum_paid_donations(project)
	disbursed = _sum_disbursements(project, STATE_DISBURSED)
	target = flt(frappe.db.get_value("Donation Project", project, "target_amount"))

	frappe.db.set_value(
		"Donation Project",
		project,
		{
			"collected_amount": collected,
			"disbursed_amount": disbursed,
			"available_balance": collected - disbursed,
			"progress_percent": flt(collected / target * 100, 2) if target else 0,
		},
		update_modified=False,
	)


def get_spendable_balance(project: str, exclude_request: str | None = None) -> float:
	"""Money that can still be promised to a new disbursement.

	= paid donations - already disbursed - approved but not yet disbursed.

	The project row is locked (SELECT ... FOR UPDATE) until the transaction ends,
	so two approvals running at the same moment cannot both spend the same riyal.
	"""
	frappe.db.sql("select name from `tabDonation Project` where name = %s for update", (project,))
	collected = _sum_paid_donations(project)
	disbursed = _sum_disbursements(project, STATE_DISBURSED)
	committed = _sum_disbursements(project, STATE_APPROVED, exclude=exclude_request)
	return flt(collected - disbursed - committed, 2)


# -------------------------------------------------------------------- donors


def update_donor_stats(donor: str | None) -> None:
	if not donor or not frappe.db.exists("Donor", donor):
		return
	total, count, last = frappe.db.sql(
		"""select coalesce(sum(amount), 0), count(name), max(paid_on)
		from `tabDonation` where donor = %s and status = %s""",
		(donor, STATUS_PAID),
	)[0]
	frappe.db.set_value(
		"Donor",
		donor,
		{"total_donated": flt(total), "donations_count": count, "last_donation_on": last},
		update_modified=False,
	)


def get_or_create_donor(full_name: str | None, mobile: str | None, email: str | None = None) -> str | None:
	"""Match a returning donor by mobile number, or create a new one.

	Returns None for anonymous donations (no mobile): no Donor record is created.
	"""
	if not mobile:
		return None

	existing = frappe.db.get_value("Donor", {"mobile": mobile}, ["name", "email"], as_dict=True)
	if existing:
		if email and not existing.email:
			frappe.db.set_value("Donor", existing.name, "email", email, update_modified=False)
		return existing.name

	donor = frappe.get_doc(
		{
			"doctype": "Donor",
			"full_name": (full_name or "").strip() or _("متبرع"),
			"mobile": mobile,
			"email": email,
		}
	)
	try:
		donor.insert(ignore_permissions=True)
	except frappe.UniqueValidationError:
		# Another request created the same donor a moment ago (mobile is unique in the DB).
		frappe.local.message_log = []
		return frappe.db.get_value("Donor", {"mobile": mobile}, "name", for_update=True)
	return donor.name


# ------------------------------------------------------------- notifications


def users_with_role(role: str) -> list[str]:
	users = frappe.get_all(
		"Has Role",
		filters={"role": role, "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	if not users:
		return []
	return frappe.get_all(
		"User",
		filters=[
			["name", "in", users],
			["name", "not in", ["Administrator", "Guest"]],
			["enabled", "=", 1],
		],
		pluck="name",
	)


def notify(users: list[str], subject: str, doc) -> None:
	"""In-app notification (the bell icon) for the next person in the workflow."""
	for user in set(u for u in users if u and u != frappe.session.user):
		try:
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"subject": subject,
					"for_user": user,
					"type": "Alert",
					"document_type": doc.doctype,
					"document_name": doc.name,
					"from_user": frappe.session.user,
				}
			).insert(ignore_permissions=True)
		except Exception:
			# A notification must never block an approval.
			frappe.log_error(title="Ataa Hub: notification failed")
