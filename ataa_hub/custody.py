"""Custody (عهدة) actions: approve & pay, reject, request close, close with a report.

Called from the Custody form and the staff dashboard. Each checks the role here,
not only in the browser.
"""

import base64
import mimetypes
import re

import frappe
from frappe import _
from frappe.utils import nowdate

from ataa_hub.accounting import get_available
from ataa_hub.ataa_hub.doctype.custody.custody import (
	STATUS_CLOSED,
	STATUS_CLOSING,
	STATUS_OPEN,
	STATUS_REJECTED,
	STATUS_REQUESTED,
)
from ataa_hub.constants import ROLE_ACCOUNTANT
from ataa_hub.spending import notify, post_journal_entry, throw_insufficient, users_with_role

ACCOUNTANT_ROLES = {ROLE_ACCOUNTANT, "System Manager"}
REPORT_FORMAT = "Ataa Custody Report"


def _require_accountant():
	if not (set(frappe.get_roles()) & ACCOUNTANT_ROLES):
		frappe.throw(_("هذا الإجراء للمحاسب فقط."), frappe.PermissionError)


def _load(name: str, *statuses):
	doc = frappe.get_doc("Custody", name)
	doc.check_permission("read")
	if statuses and doc.status not in statuses:
		frappe.throw(_("حالة العهدة الآن: {0}.").format(_(doc.status)))
	return doc


def _set_status(doc, status, **values):
	doc.status = status
	doc.update(values)
	doc.flags.status_change = True
	doc.flags.ignore_permissions = True
	doc.save()


def notify_accountants(doc, subject):
	notify(users_with_role(ROLE_ACCOUNTANT), subject, doc)


# ------------------------------------------------------------------ actions


@frappe.whitelist()
def approve_and_pay(name: str) -> str:
	"""Accountant: hand the cash over. Checks the project's available balance under a lock."""
	_require_accountant()
	doc = _load(name, STATUS_REQUESTED)
	available = get_available(doc.project)  # locks the project row
	if doc.amount > available:
		throw_insufficient(doc.amount, available, doc.project_title)

	settings = frappe.get_cached_doc("Ataa Settings")
	custody_account = settings.custody_account
	bank = settings.main_bank_account
	if not custody_account or not bank:
		frappe.throw(_("حدد حساب العهد والحساب البنكي في إعدادات عطاء."))
	je = post_journal_entry(
		doc,
		[(custody_account, doc.amount, 0, doc.project), (bank, 0, doc.amount, doc.project)],
		f"صرف عهدة {doc.name} إلى {doc.holder_name or doc.holder}",
	)
	_set_status(
		doc,
		STATUS_OPEN,
		custody_account=custody_account,
		paid_from_account=bank,
		expense_account=settings.disbursement_expense_account,
		pay_journal_entry=je.name,
		paid_on=nowdate(),
	)
	notify([doc.holder], _("صُرفت عهدتك {0}. سجّل مشترياتك وفواتيرها فيها.").format(doc.name), doc)
	return doc.status


@frappe.whitelist()
def reject(name: str, reason: str) -> str:
	_require_accountant()
	if not (reason or "").strip():
		frappe.throw(_("اكتب سبب الرفض."))
	doc = _load(name, STATUS_REQUESTED)
	_set_status(doc, STATUS_REJECTED, reject_reason=reason.strip())
	notify([doc.holder], _("رُفض طلب العهدة {0}: {1}").format(doc.name, reason.strip()), doc)
	return doc.status


@frappe.whitelist()
def request_close(name: str) -> str:
	"""The holder (or the accountant) says the custody is done."""
	doc = _load(name, STATUS_OPEN)
	if doc.holder != frappe.session.user:
		_require_accountant()
	request_close_for(doc)
	return doc.status


def request_close_for(doc, automatic=False):
	_set_status(doc, STATUS_CLOSING)
	why = _("صُرفت بالكامل") if automatic else _("طلب صاحبها إقفالها")
	notify_accountants(doc, _("العهدة {0} {1}. هل تريد إقفالها؟").format(doc.name, why))


@frappe.whitelist()
def close(name: str) -> str:
	"""Accountant: book the purchases on the project, take back the cash left, attach the report."""
	_require_accountant()
	doc = _load(name, STATUS_OPEN, STATUS_CLOSING)
	missing = [str(r.idx) for r in doc.expenses if not r.invoice]
	if missing:
		frappe.throw(_("أرفق فاتورة لكل شراء قبل الإقفال (الأسطر: {0}).").format(", ".join(missing)))

	lines = []
	if doc.spent:
		lines.append((doc.expense_account, doc.spent, 0, doc.project))
	if doc.remaining:
		lines.append((doc.paid_from_account, doc.remaining, 0, doc.project))
	lines.append((doc.custody_account, 0, doc.amount, doc.project))
	je = post_journal_entry(doc, lines, f"تسوية عهدة {doc.name}: مشتريات {doc.spent}، مرتجع {doc.remaining}")

	_set_status(
		doc, STATUS_CLOSED, close_journal_entry=je.name, closed_on=nowdate(), closed_by=frappe.session.user
	)
	doc.db_set("report_file", _attach_report(doc), update_modified=False)
	notify([doc.holder], _("أُقفلت عهدتك {0}.").format(doc.name), doc)
	return doc.status


def _attach_report(doc) -> str | None:
	try:
		from frappe.utils.pdf import get_pdf

		html = frappe.get_print("Custody", doc.name, REPORT_FORMAT, no_letterhead=1)
		# Self-contained: the report's CSS is inline and invoices are data URIs, so drop
		# stylesheet links the renderer would have to fetch from the site's own host.
		html = re.sub(r"<link[^>]*>", "", html)
		pdf = get_pdf(html)
	except Exception:
		frappe.log_error(title=f"Custody report failed for {doc.name}")
		return None
	f = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{doc.name}-report.pdf",
			"content": pdf,
			"is_private": 1,
			"attached_to_doctype": "Custody",
			"attached_to_name": doc.name,
		}
	).insert(ignore_permissions=True)
	return f.file_url


# ------------------------------------------------------------------ report helpers


def invoice_data_uri(file_url: str | None) -> str | None:
	"""Jinja helper for the report: embed an invoice image (the PDF renderer cannot log in
	to fetch private files). Non-image invoices return None and are listed by name."""
	if not file_url:
		return None
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		return None
	mime = mimetypes.guess_type(file_url)[0] or ""
	if not mime.startswith("image/"):
		return None
	content = frappe.get_doc("File", name).get_content()
	if isinstance(content, str):
		content = content.encode()
	return f"data:{mime};base64,{base64.b64encode(content).decode()}"
