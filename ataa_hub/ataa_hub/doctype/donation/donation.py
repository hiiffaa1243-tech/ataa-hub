import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from ataa_hub.constants import (
	CHANNEL_BANK_TRANSFER,
	CHANNEL_POS,
	PROJECT_ACTIVE,
	STATUS_FAILED,
	STATUS_PAID,
	STATUS_PENDING,
	STATUS_REFUNDED,
)
from ataa_hub.services import update_donor_stats, update_project_totals

# Which status changes are allowed (PRD 5.3: a paid donation is only ever refunded, never edited)
ALLOWED_TRANSITIONS = {
	STATUS_PENDING: {STATUS_PENDING, STATUS_PAID, STATUS_FAILED},
	STATUS_PAID: {STATUS_PAID, STATUS_REFUNDED},
	STATUS_FAILED: {STATUS_FAILED},
	STATUS_REFUNDED: {STATUS_REFUNDED},
}

# Fields frozen once money has been received
LOCKED_AFTER_PAYMENT = (
	"project",
	"amount",
	"channel",
	"donor",
	"api_client",
	"external_reference",
	"payment_reference",
)


class Donation(Document):
	def validate(self):
		self.amount = flt(self.amount, 2)
		if self.amount <= 0:
			frappe.throw(_("مبلغ التبرع يجب أن يكون أكبر من صفر."))

		if self.is_new():
			self.validate_new_donation()
		else:
			self.validate_status_change()

		self.validate_channel_fields()

		if self.status == STATUS_PAID and not self.paid_on:
			self.paid_on = now_datetime()

		if self.status == STATUS_REFUNDED and not (self.refund_reason or "").strip():
			frappe.throw(_("اكتب سبب الاسترداد."))

		if self.donor and not self.donor_name:
			self.donor_name = frappe.db.get_value("Donor", self.donor, "full_name")

	def validate_new_donation(self):
		project_status = frappe.db.get_value("Donation Project", self.project, "status")
		if project_status != PROJECT_ACTIVE:
			frappe.throw(
				_("المشروع {0} غير نشط، ولا يقبل تبرعات.").format(frappe.bold(self.project)),
				title=_("مشروع غير نشط"),
			)

		# Online channels arrive through the API / payment gateway (flag set in code).
		# A person in the desk can only record bank transfers manually.
		if self.channel != CHANNEL_BANK_TRANSFER and not self.flags.from_integration:
			frappe.throw(_("الإدخال اليدوي متاح للتحويلات البنكية فقط. القنوات الأخرى تصل عبر الربط."))

		if self.status == STATUS_REFUNDED:
			frappe.throw(_("لا يمكن إنشاء تبرع بحالة مسترد."))

	def validate_status_change(self):
		before = self.get_doc_before_save()
		if not before:
			return

		allowed = ALLOWED_TRANSITIONS.get(before.status, {before.status})
		if self.status not in allowed:
			frappe.throw(
				_("لا يمكن تغيير حالة التبرع من {0} إلى {1}.").format(_(before.status), _(self.status)),
				title=_("تغيير غير مسموح"),
			)

		if before.status in (STATUS_PAID, STATUS_REFUNDED):
			for field in LOCKED_AFTER_PAYMENT:
				old, new = before.get(field), self.get(field)
				changed = flt(old) != flt(new) if field == "amount" else (old or "") != (new or "")
				if changed:
					frappe.throw(
						_("لا يمكن تعديل «{0}» بعد استلام التبرع. للإلغاء غيّري الحالة إلى مسترد.").format(
							_(self.meta.get_label(field))
						)
					)

	def validate_channel_fields(self):
		if self.channel == CHANNEL_POS:
			missing = [f for f in ("terminal_id", "card_scheme", "rrn") if not self.get(f)]
			if missing:
				frappe.throw(_("تبرعات نقاط البيع تحتاج: {0}").format(", ".join(missing)))

		if self.channel == CHANNEL_BANK_TRANSFER and self.status == STATUS_PAID and not self.transfer_proof:
			frappe.throw(_("أرفقي إثبات التحويل قبل تأكيد استلام المبلغ."))

	def on_update(self):
		before = self.get_doc_before_save()
		was_paid = bool(before and before.status == STATUS_PAID)

		# Balances only move when money is actually in (Paid) or given back (Refunded).
		if self.status in (STATUS_PAID, STATUS_REFUNDED) or was_paid:
			update_project_totals(self.project)
			update_donor_stats(self.donor)

	def on_trash(self):
		if self.status in (STATUS_PAID, STATUS_REFUNDED):
			frappe.throw(
				_("التبرع المدفوع لا يُحذف. لإلغائه غيّري حالته إلى مسترد مع ذكر السبب."),
				title=_("حذف غير مسموح"),
			)


def on_doctype_update():
	"""Database-level guarantee against duplicates (PRD 5.3, API.md section 7).

	The application also checks before inserting, but only a UNIQUE index still
	holds when two identical requests arrive at the same millisecond.
	"""
	frappe.db.add_unique(
		"Donation", ["api_client", "external_reference"], constraint_name="unique_client_reference"
	)
	frappe.db.add_index("Donation", ["project", "status"])
	frappe.db.add_index("Donation", ["payment_reference"])
