import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, fmt_money, today

from ataa_hub.constants import (
	PROJECT_ACTIVE,
	PROJECT_COMPLETED,
	ROLE_ACCOUNTANT,
	ROLE_EXECUTIVE,
	STATE_APPROVED,
	STATE_DISBURSED,
	STATE_DRAFT,
	STATE_PENDING_ACCOUNTANT,
	STATE_PENDING_EXECUTIVE,
	STATE_REJECTED,
)
from ataa_hub.services import get_spendable_balance, notify, update_project_totals, users_with_role

# Every time the request moves forward to one of these states, the balance is checked again
# (PRD 6.5: "عند التقديم وعند الاعتماد: المبلغ يجب ألا يتجاوز الرصيد المتاح").
BALANCE_CHECK_STATES = (STATE_PENDING_ACCOUNTANT, STATE_PENDING_EXECUTIVE, STATE_APPROVED)


class DisbursementRequest(Document):
	# ------------------------------------------------------------ validation

	def validate(self):
		self.amount = flt(self.amount, 2)
		if self.amount <= 0:
			frappe.throw(_("المبلغ المطلوب يجب أن يكون أكبر من صفر."))

		if not self.requested_by:
			self.requested_by = frappe.session.user

		project_status = frappe.db.get_value("Donation Project", self.project, "status")
		if project_status not in (PROJECT_ACTIVE, PROJECT_COMPLETED):
			frappe.throw(_("لا يمكن الصرف من مشروع حالته {0}.").format(_(project_status)))

		state = self.workflow_state or STATE_DRAFT
		if state != self.previous_state() and state in BALANCE_CHECK_STATES:
			self.check_balance(snapshot=(state == STATE_PENDING_ACCOUNTANT))

		if state == STATE_REJECTED and not (self.rejection_reason or "").strip():
			frappe.throw(
				_("اكتب سبب الرفض في حقل «سبب الرفض» ثم احفظ قبل الرفض."), title=_("سبب الرفض مطلوب")
			)

	def check_balance(self, snapshot: bool = False):
		balance = get_spendable_balance(self.project, exclude_request=self.name)
		if snapshot:
			self.available_balance_at_request = balance
		if self.amount > balance:
			frappe.throw(
				_("المبلغ المطلوب {0} يتجاوز الرصيد المتاح للمشروع {1}.").format(
					frappe.bold(fmt_money(self.amount, currency="SAR")),
					frappe.bold(fmt_money(balance, currency="SAR")),
				),
				title=_("رصيد غير كافٍ"),
			)

	def before_update_after_submit(self):
		if self.workflow_state == STATE_DISBURSED and self.previous_state() != STATE_DISBURSED:
			self.disbursed_on = today()

	# -------------------------------------------------------------- effects

	def on_change(self):
		"""Runs after every save / submit / update-after-submit / cancel."""
		previous = self.previous_state()
		if self.workflow_state == previous:
			return

		# PRD 6.5: the project balance goes down only when the money is actually paid out.
		if STATE_DISBURSED in (self.workflow_state, previous):
			update_project_totals(self.project)

		self.notify_next_person(previous)

	def on_cancel(self):
		update_project_totals(self.project)

	def previous_state(self):
		before = self.get_doc_before_save()
		return before.workflow_state if before else None

	def notify_next_person(self, previous):
		state = self.workflow_state
		amount = fmt_money(self.amount, currency="SAR")
		title = self.project_title or self.project

		if state == STATE_PENDING_ACCOUNTANT:
			notify(
				users_with_role(ROLE_ACCOUNTANT),
				_("طلب صرف {0} لمشروع {1} بانتظار مراجعتك").format(amount, title),
				self,
			)
		elif state == STATE_PENDING_EXECUTIVE:
			notify(
				users_with_role(ROLE_EXECUTIVE),
				_("طلب صرف {0} لمشروع {1} بانتظار اعتمادك").format(amount, title),
				self,
			)
		elif state == STATE_APPROVED:
			notify(
				users_with_role(ROLE_ACCOUNTANT),
				_("طلب الصرف {0} معتمد وبانتظار تأكيد الصرف").format(self.name),
				self,
			)
			notify([self.requested_by], _("تم اعتماد طلب الصرف {0}").format(self.name), self)
		elif state == STATE_REJECTED:
			notify(
				[self.requested_by],
				_("تم رفض طلب الصرف {0}: {1}").format(self.name, self.rejection_reason),
				self,
			)
		elif state == STATE_DRAFT and previous == STATE_PENDING_ACCOUNTANT:
			notify([self.requested_by], _("أعاد المحاسب طلب الصرف {0} للتعديل").format(self.name), self)
		elif state == STATE_DISBURSED:
			notify([self.requested_by], _("تم صرف مبلغ طلب الصرف {0}").format(self.name), self)
