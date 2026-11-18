"""Custody (عهدة): cash advanced to a staff member for a project, settled with invoices.

    Requested ─(Accountant: approve & pay)→ Open      JE: Dr Staff Custody / Cr Bank
              ─(Accountant: reject, reason)→ Rejected
    Open: the holder logs each purchase (amount + invoice); spent/remaining update live.
          When nothing remains (or the holder asks) → Closing Requested, accountant notified.
    Closing Requested ─(Accountant: close)→ Closed
          JE: Dr Project Program Expenses (spent) + Dr Bank (cash returned) / Cr Staff Custody
          and a PDF report of every purchase with its invoice is attached.

While open, the custody amount counts as committed on the project (accounting.
get_open_custody_amount), so the same riyal cannot also be approved for a disbursement.
Status only changes through the functions in ataa_hub.custody.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

STATUS_REQUESTED = "Requested"
STATUS_REJECTED = "Rejected"
STATUS_OPEN = "Open"
STATUS_CLOSING = "Closing Requested"
STATUS_CLOSED = "Closed"


class Custody(Document):
	def validate(self):
		settings = frappe.get_cached_doc("Ataa Settings")
		self.company = self.company or settings.company
		self.amount = flt(self.amount, 2)
		if self.amount <= 0:
			frappe.throw(_("مبلغ العهدة يجب أن يكون أكبر من صفر."))
		if self.is_new():
			self.holder = frappe.session.user
			self.holder_name = frappe.utils.get_fullname(self.holder)
			self.status = STATUS_REQUESTED
		self.validate_project()
		self.guard_changes()
		self.update_totals()

	def validate_project(self):
		project = frappe.db.get_value("Project", self.project, ["status", "fund_type"], as_dict=True)
		if not project or project.status == "Cancelled" or not project.fund_type:
			frappe.throw(_("لا يمكن طلب عهدة على هذا المشروع."))

	def guard_changes(self):
		"""Only the status functions move the status; purchases only while the custody is open."""
		if self.is_new() or self.flags.status_change:
			return
		before = self.get_doc_before_save()
		if before.status != self.status:
			frappe.throw(_("تتغير حالة العهدة من أزرارها فقط."))
		if self.status != STATUS_REQUESTED and flt(before.amount) != self.amount:
			frappe.throw(_("لا يمكن تعديل مبلغ العهدة بعد صرفها."))
		if self.status != STATUS_OPEN and _rows(before) != _rows(self):
			frappe.throw(_("تُسجَّل المشتريات والعهدة مفتوحة فقط."))

	def update_totals(self):
		for row in self.expenses:
			row.amount = flt(row.amount, 2)
			if row.amount <= 0:
				frappe.throw(_("مبلغ الشراء في السطر {0} يجب أن يكون أكبر من صفر.").format(row.idx))
		self.spent = flt(sum(r.amount for r in self.expenses), 2)
		if self.spent > self.amount:
			frappe.throw(
				_("المشتريات ({0}) تتجاوز مبلغ العهدة ({1}).").format(
					frappe.format_value(self.spent, {"fieldtype": "Currency", "options": "SAR"}),
					frappe.format_value(self.amount, {"fieldtype": "Currency", "options": "SAR"}),
				)
			)
		self.remaining = flt(self.amount - self.spent, 2)

	def after_insert(self):
		from ataa_hub.custody import notify_accountants

		notify_accountants(self, _("طلب عهدة جديد {0} بمبلغ {1}").format(self.name, self.amount))

	def on_update(self):
		# Spent in full: ask the accountant to close it, no button needed.
		if (
			self.status == STATUS_OPEN
			and self.expenses
			and self.remaining <= 0
			and not self.flags.status_change
		):
			from ataa_hub.custody import request_close_for

			request_close_for(self, automatic=True)

	def on_trash(self):
		if self.status not in (STATUS_REQUESTED, STATUS_REJECTED):
			frappe.throw(_("لا يمكن حذف عهدة صُرفت."))


def _rows(doc) -> list:
	return [
		(r.expense_date and str(r.expense_date), r.description, r.supplier_name, flt(r.amount), r.invoice)
		for r in doc.expenses
	]
