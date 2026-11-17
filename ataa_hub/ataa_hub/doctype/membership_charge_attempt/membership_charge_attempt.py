"""Membership Charge Attempt: one row per try to charge a membership invoice (PRD D8, §7.5.3).

The record is created in Processing and committed *before* Moyasar is called, so
a crash never leaves a charge without a trace. Rows are written by the system;
the accountant can only add review notes or close a Needs Review row.
"""

import frappe
from frappe import _
from frappe.model.document import Document

PROCESSING = "Processing"
SUCCEEDED = "Succeeded"
FAILED = "Failed"
NEEDS_REVIEW = "Needs Review"


class MembershipChargeAttempt(Document):
	def validate(self):
		if self.is_new() or self.flags.from_charge_job:
			return
		before = self.get_doc_before_save()
		if before and before.status != self.status:
			# Manual change: only a Needs Review row may be closed, and only as Failed
			# (the accountant checked Moyasar: nothing was charged).
			if not (before.status == NEEDS_REVIEW and self.status == FAILED):
				frappe.throw(_("حالة محاولة الخصم يغيّرها النظام فقط."))
			if not self.review_notes:
				frappe.throw(_("اكتب ملاحظة المراجعة قبل إغلاق المحاولة."))
