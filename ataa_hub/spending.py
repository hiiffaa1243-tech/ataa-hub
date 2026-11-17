"""Shared helpers for the spending documents (Disbursement Request, Fund Allocation)."""

import frappe
from frappe import _
from frappe.utils import fmt_money


def previous_state(doc) -> str | None:
	before = doc.get_doc_before_save()
	return before.workflow_state if before else None


def state_changed(doc) -> bool:
	return bool(doc.workflow_state) and doc.workflow_state != previous_state(doc)


def sar(amount) -> str:
	return fmt_money(amount, currency="SAR")


def throw_insufficient(amount, available, what=None):
	frappe.throw(
		_("المبلغ {0} يتجاوز الرصيد المتاح {1}{2}.").format(
			frappe.bold(sar(amount)), frappe.bold(sar(available)), f" ({what})" if what else ""
		),
		title=_("رصيد غير كافٍ"),
	)


def users_with_role(role: str) -> list[str]:
	return frappe.get_all(
		"Has Role",
		filters={"role": role, "parenttype": "User", "parent": ("not in", ("Administrator", "Guest"))},
		pluck="parent",
		distinct=True,
	)


def notify(users, subject: str, doc) -> None:
	"""In-app notification (the bell icon) for the next person in the workflow."""
	for user in {u for u in users if u and u != frappe.session.user}:
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


def post_journal_entry(source, lines, remark: str):
	"""Insert and submit a Journal Entry that links back to `source`.

	lines: [(account, debit, credit, project), ...]
	"""
	cost_center = frappe.get_cached_value("Company", source.company, "cost_center")
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": source.company,
			"posting_date": frappe.utils.nowdate(),
			"user_remark": remark,
			"ataa_reference_doctype": source.doctype,
			"ataa_reference_name": source.name,
			"accounts": [
				{
					"account": account,
					"debit_in_account_currency": debit,
					"credit_in_account_currency": credit,
					"project": project,
					"cost_center": cost_center,
				}
				for account, debit, credit, project in lines
			],
		}
	)
	je.flags.ignore_permissions = True
	je.flags.from_ataa_document = True
	je.insert()
	je.submit()
	return je


def cancel_journal_entry(name: str | None) -> None:
	if name and frappe.db.get_value("Journal Entry", name, "docstatus") == 1:
		je = frappe.get_doc("Journal Entry", name)
		je.flags.ignore_permissions = True
		je.flags.from_ataa_document = True
		je.cancel()
