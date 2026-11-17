"""Donation: one received gift of money, booked to the General Ledger on submit (PRD §5.2, §6.1, D7).

Life cycle (Frappe docstatus, no custom status machine):
- Draft (0): pending. Website donations wait here for Moyasar; bank transfers wait
  for the accountant to see the money on the statement.
- Submitted (1): money received. A Journal Entry is posted:
      Dr  channel's Mode of Payment account   (project)
      Cr  Restricted / Unrestricted Donations Income   (project)
- Cancelled (2): refund or correction. The Journal Entry is cancelled, which
  reverses the GL. A reason is required. Submitted and cancelled donations are
  never deleted.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from ataa_hub.constants import CHANNEL_BANK_TRANSFER, CHANNEL_POS, FUND_UNRESTRICTED
from ataa_hub.donors import update_lifetime_giving

CHANNEL_TO_SETTINGS_FIELD = {
	"Website": "mop_website",
	"Online Store": "mop_online_store",
	"POS": "mop_pos",
	"Bank Transfer": "mop_bank_transfer",
	"Partner": "mop_partner",
}
POS_FIELDS = ("terminal_id", "card_scheme", "rrn")


class Donation(Document):
	# ----------------------------------------------------------------- validate

	def validate(self):
		settings = frappe.get_cached_doc("Ataa Settings")
		self.company = self.company or settings.company
		self.amount = flt(self.amount, 2)
		if self.amount <= 0:
			frappe.throw(_("مبلغ التبرع يجب أن يكون أكبر من صفر."))

		if self.is_new() and self.channel != CHANNEL_BANK_TRANSFER and not self.flags.from_integration:
			# Online channels arrive through the API / payment gateway only.
			frappe.throw(_("الإدخال اليدوي متاح للتحويلات البنكية فقط. القنوات الأخرى تصل عبر الربط."))

		self.validate_project()
		self.mode_of_payment = settings.get(CHANNEL_TO_SETTINGS_FIELD[self.channel])
		if not self.mode_of_payment:
			frappe.throw(_("لم تُحدَّد طريقة دفع لقناة {0} في إعدادات عطاء.").format(_(self.channel)))

		if self.channel == CHANNEL_POS:
			missing = [f for f in POS_FIELDS if not self.get(f)]
			if missing:
				frappe.throw(_("تبرعات نقاط البيع تحتاج: {0}").format(", ".join(missing)))

		if self.donor and not self.donor_name:
			self.donor_name = frappe.db.get_value("Customer", self.donor, "customer_name")

	def validate_project(self):
		project = frappe.db.get_value(
			"Project",
			self.project,
			["status", "is_active", "is_public", "fund_type", "company"],
			as_dict=True,
		)
		if not project:
			frappe.throw(_("المشروع غير موجود."))
		if (
			project.status != "Open"
			or project.is_active != "Yes"
			or not project.is_public
			or not project.fund_type
		):
			frappe.throw(
				_("المشروع {0} لا يستقبل تبرعات حالياً.").format(frappe.bold(self.project)),
				title=_("مشروع لا يستقبل تبرعات"),
			)
		if project.company and project.company != self.company:
			frappe.throw(_("المشروع يتبع شركة أخرى."))
		self.fund_type = project.fund_type

	# ------------------------------------------------------------------- submit

	def before_submit(self):
		if self.channel == CHANNEL_BANK_TRANSFER and not self.transfer_proof:
			frappe.throw(_("أرفقي إثبات التحويل قبل تأكيد استلام المبلغ."), title=_("إثبات التحويل مطلوب"))
		self.payment_status = "Paid"
		self.paid_at = self.paid_at or now_datetime()
		self.freeze_impact()
		self.receipt_token = self.receipt_token or frappe.generate_hash(length=32)

	def freeze_impact(self):
		"""Impact is fixed at the moment of giving; later rate changes don't rewrite history."""
		label, rate = frappe.db.get_value(
			"Project", self.project, ["impact_unit_label", "impact_units_per_sar"]
		)
		self.impact_unit_label = label
		self.impact_units = flt(self.amount * flt(rate), 2) if rate else 0

	def on_submit(self):
		je = self.make_journal_entry()
		self.db_set("journal_entry", je.name, update_modified=False)
		update_lifetime_giving(self.donor)

	def make_journal_entry(self):
		settings = frappe.get_cached_doc("Ataa Settings")
		debit_account = get_mode_of_payment_account(self.mode_of_payment, self.company)
		credit_account = (
			settings.unrestricted_income_account
			if self.fund_type == FUND_UNRESTRICTED
			else settings.restricted_income_account
		)
		cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
		row = {"project": self.project, "cost_center": cost_center}
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"company": self.company,
				"posting_date": self.posting_date,
				"cheque_no": self.payment_reference or self.name,
				"cheque_date": self.posting_date,
				"mode_of_payment": self.mode_of_payment,
				"user_remark": _("تبرع {0} لمشروع {1} عبر {2}").format(
					self.name, self.project_title, _(self.channel)
				),
				"ataa_reference_doctype": self.doctype,
				"ataa_reference_name": self.name,
				"accounts": [
					{**row, "account": debit_account, "debit_in_account_currency": self.amount},
					{**row, "account": credit_account, "credit_in_account_currency": self.amount},
				],
			}
		)
		je.flags.ignore_permissions = True
		je.flags.from_ataa_document = True
		je.insert()
		je.submit()
		return je

	# ------------------------------------------------------------------- cancel

	def before_cancel(self):
		if not (self.cancel_reason or "").strip():
			frappe.throw(_("اكتبي سبب الإلغاء أو الاسترداد قبل الإلغاء."), title=_("السبب مطلوب"))
		# The JE links back to this donation; we cancel it ourselves in on_cancel.
		self.ignore_linked_doctypes = ("Journal Entry", "GL Entry", "Payment Ledger Entry")

	def on_cancel(self):
		if self.journal_entry and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
			je = frappe.get_doc("Journal Entry", self.journal_entry)
			je.flags.ignore_permissions = True
			je.flags.from_ataa_document = True
			je.cancel()
		self.db_set("payment_status", "Refunded", update_modified=False)
		update_lifetime_giving(self.donor)

	def on_trash(self):
		if self.docstatus != 0:
			frappe.throw(_("التبرع المستلم لا يُحذف. يمكن إلغاؤه مع ذكر السبب."), title=_("حذف غير مسموح"))


def get_mode_of_payment_account(mode_of_payment, company):
	account = frappe.db.get_value(
		"Mode of Payment Account", {"parent": mode_of_payment, "company": company}, "default_account"
	)
	if not account:
		frappe.throw(_("طريقة الدفع {0} ليس لها حساب في الشركة {1}.").format(mode_of_payment, company))
	return account
