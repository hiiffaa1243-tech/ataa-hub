"""Disbursement Request: spending from a project, through a 4-step approval (PRD §7.8).

    Draft ─(PM: Submit for Review)→ Pending Accountant Review
          ─(Accountant: Approve)→ Pending Executive Approval   (or Return → Draft)
          ─(Executive: Approve)→ Approved [submitted]          (or Reject, reason required)
          ─(Accountant: Mark Paid)→ Paid  → Journal Entry: Dr expense / Cr bank (project)

At every forward step the amount is checked against available(project) with the
project row locked, so two approvals can never spend the same riyal (PRD §6.3).
"Approved" money is committed: it is excluded from available() until it is paid.

If the payment Journal Entry is cancelled (wrong bank, wrong amount...), the
request goes back to Approved and can be paid again (hook in overrides/journal_entry.py).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from ataa_hub.accounting import get_available
from ataa_hub.constants import (
	ROLE_ACCOUNTANT,
	ROLE_EXECUTIVE,
	STATE_APPROVED,
	STATE_DRAFT,
	STATE_PAID,
	STATE_PENDING_ACCOUNTANT,
	STATE_PENDING_EXECUTIVE,
	STATE_REJECTED,
)
from ataa_hub.spending import (
	notify,
	post_journal_entry,
	previous_state,
	sar,
	state_changed,
	throw_insufficient,
	users_with_role,
)

# Forward steps that re-check the balance (PRD §6.3).
CHECKED_STATES = (STATE_PENDING_ACCOUNTANT, STATE_PENDING_EXECUTIVE, STATE_APPROVED, STATE_PAID)


class DisbursementRequest(Document):
	# ------------------------------------------------------------ validation

	def validate(self):
		settings = frappe.get_cached_doc("Ataa Settings")
		self.company = self.company or settings.company
		self.amount = flt(self.amount, 2)
		if self.amount <= 0:
			frappe.throw(_("المبلغ المطلوب يجب أن يكون أكبر من صفر."))
		self.requested_by = self.requested_by or frappe.session.user
		self.expense_account = self.expense_account or settings.disbursement_expense_account
		self.paid_from_account = self.paid_from_account or settings.main_bank_account

		self.validate_project()
		self.validate_accounts()

		if state_changed(self):
			self.on_state_change()

	def validate_project(self):
		project = frappe.db.get_value(
			"Project", self.project, ["status", "fund_type", "company"], as_dict=True
		)
		if not project or project.status == "Cancelled" or not project.fund_type:
			frappe.throw(_("لا يمكن الصرف من هذا المشروع."))
		if project.company and project.company != self.company:
			frappe.throw(_("المشروع يتبع شركة أخرى."))

	def validate_accounts(self):
		expense = frappe.db.get_value(
			"Account", self.expense_account, ["root_type", "company", "is_group"], as_dict=True
		)
		if (
			not expense
			or expense.root_type != "Expense"
			or expense.is_group
			or expense.company != self.company
		):
			frappe.throw(_("حساب المصروف يجب أن يكون حساب مصروفات فرعياً في شركة الجمعية."))
		if self.paid_from_account:
			bank = frappe.db.get_value(
				"Account", self.paid_from_account, ["account_type", "company", "is_group"], as_dict=True
			)
			if (
				not bank
				or bank.account_type not in ("Bank", "Cash")
				or bank.is_group
				or bank.company != self.company
			):
				frappe.throw(_("حساب الصرف يجب أن يكون حساب بنك أو صندوق في شركة الجمعية."))

	def on_state_change(self):
		state = self.workflow_state
		if state in CHECKED_STATES:
			self.check_balance(snapshot=state == STATE_PENDING_ACCOUNTANT)
		if state == STATE_REJECTED and not (self.rejection_reason or "").strip():
			frappe.throw(_("اكتب سبب الرفض في حقله واحفظ، ثم ارفض."), title=_("سبب الرفض مطلوب"))
		if state == STATE_PAID and not self.paid_from_account:
			frappe.throw(_("اختر حساب البنك الذي صُرف منه المبلغ."))

	def check_balance(self, snapshot: bool = False):
		# Own amount is excluded: once Approved, this request is itself part of "committed".
		available = get_available(self.project, exclude_request=self.name)
		if snapshot:
			self.available_balance_at_request = available
		if self.amount > available:
			throw_insufficient(self.amount, available, self.project_title or self.project)

	# ---------------------------------------------------------------- payment

	def before_update_after_submit(self):
		# Approved (docstatus 1) → Paid is an update after submit.
		if state_changed(self):
			self.on_state_change()
			if self.workflow_state == STATE_PAID:
				self.paid_on = nowdate()

	def on_update_after_submit(self):
		if self.workflow_state == STATE_PAID and not self.journal_entry:
			je = post_journal_entry(
				self,
				[
					(self.expense_account, self.amount, 0, self.project),
					(self.paid_from_account, 0, self.amount, self.project),
				],
				_("صرف {0} لمشروع {1}: {2}").format(self.name, self.project_title, self.purpose),
			)
			self.db_set("journal_entry", je.name, update_modified=False)

	def before_cancel(self):
		if self.journal_entry and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
			frappe.throw(
				_("هذا الطلب مصروف. ألغ قيد الصرف {0} أولاً (يرجع الطلب إلى «معتمد») ثم ألغ الطلب.").format(
					frappe.bold(self.journal_entry)
				)
			)

	# ---------------------------------------------------------- notifications

	def on_change(self):
		previous = previous_state(self)
		if not self.workflow_state or self.workflow_state == previous:
			return
		amount, title, state = sar(self.amount), self.project_title or self.project, self.workflow_state
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
		elif state == STATE_APPROVED and previous == STATE_PENDING_EXECUTIVE:
			notify(
				users_with_role(ROLE_ACCOUNTANT),
				_("طلب الصرف {0} معتمد وبانتظار الصرف").format(self.name),
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
		elif state == STATE_PAID:
			notify([self.requested_by], _("تم صرف مبلغ طلب الصرف {0}").format(self.name), self)


def on_payment_journal_cancelled(request_name: str, journal_entry: str) -> None:
	"""Called when someone cancels the payment Journal Entry: the request can be paid again."""
	request = frappe.get_doc("Disbursement Request", request_name)
	if request.journal_entry != journal_entry:
		return
	request.db_set(
		{"workflow_state": STATE_APPROVED, "journal_entry": None, "paid_on": None}, update_modified=True
	)
	request.add_comment(
		"Info", _("أُلغي قيد الصرف {0}، فرجع الطلب إلى «معتمد» ويمكن صرفه من جديد.").format(journal_entry)
	)
