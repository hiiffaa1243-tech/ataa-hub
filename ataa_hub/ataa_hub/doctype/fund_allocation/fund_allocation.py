"""Fund Allocation: the only way unrestricted money reaches a restricted project (PRD §6.3, §7.9, D3).

    Draft ─(PM or Accountant: Request)→ Pending Executive Approval
          ─(Executive: Approve)→ Approved [submitted] → Journal Entry
          ─(Executive: Reject, reason required)→ Rejected

The Journal Entry moves the balance between projects on two contra-income accounts:
    Dr Fund Transfers Out (from: GENERAL)   Cr Fund Transfers In (to: restricted project)
so balance(GENERAL) goes down and balance(target) goes up by the same amount, while
"donation income" (progress bars) is untouched. Cancelling the allocation reverses it.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from ataa_hub.accounting import get_available
from ataa_hub.constants import (
	FUND_RESTRICTED,
	FUND_UNRESTRICTED,
	ROLE_EXECUTIVE,
	STATE_APPROVED,
	STATE_PENDING_EXECUTIVE,
	STATE_REJECTED,
)
from ataa_hub.spending import (
	cancel_journal_entry,
	notify,
	post_journal_entry,
	previous_state,
	sar,
	state_changed,
	throw_insufficient,
	users_with_role,
)


class FundAllocation(Document):
	def validate(self):
		settings = frappe.get_cached_doc("Ataa Settings")
		self.company = self.company or settings.company
		self.from_project = self.from_project or settings.general_project
		self.requested_by = self.requested_by or frappe.session.user
		self.amount = flt(self.amount, 2)
		if self.amount <= 0:
			frappe.throw(_("المبلغ يجب أن يكون أكبر من صفر."))
		self.validate_projects()

		if state_changed(self):
			state = self.workflow_state
			if state in (STATE_PENDING_EXECUTIVE, STATE_APPROVED):
				self.check_balance(snapshot=state == STATE_PENDING_EXECUTIVE)
			if state == STATE_REJECTED and not (self.rejection_reason or "").strip():
				frappe.throw(_("اكتب سبب الرفض في حقله واحفظ، ثم ارفض."), title=_("سبب الرفض مطلوب"))

	def validate_projects(self):
		if self.from_project == self.to_project:
			frappe.throw(_("لا يمكن التحويل من المشروع إلى نفسه."))
		source = frappe.db.get_value("Project", self.from_project, ["fund_type", "company"], as_dict=True)
		target = frappe.db.get_value(
			"Project", self.to_project, ["fund_type", "company", "status"], as_dict=True
		)
		if not source or source.fund_type != FUND_UNRESTRICTED:
			frappe.throw(_("التحويل يكون من صندوق غير مقيّد فقط (مثل الصندوق العام)."))
		if not target or target.fund_type != FUND_RESTRICTED or target.status == "Cancelled":
			frappe.throw(_("التحويل يكون إلى مشروع مقيّد قائم فقط."))
		if self.company not in (source.company or self.company, target.company or self.company):
			frappe.throw(_("المشروعان يجب أن يتبعا شركة الجمعية."))

	def check_balance(self, snapshot: bool = False):
		available = get_available(self.from_project)
		if snapshot:
			self.available_at_request = available
		if self.amount > available:
			throw_insufficient(self.amount, available, _("الصندوق العام"))

	def on_submit(self):
		settings = frappe.get_cached_doc("Ataa Settings")
		je = post_journal_entry(
			self,
			[
				(settings.fund_transfers_out_account, self.amount, 0, self.from_project),
				(settings.fund_transfers_in_account, 0, self.amount, self.to_project),
			],
			_("تخصيص {0} من {1} إلى {2}: {3}").format(
				self.name, self.from_project, self.to_project_title, self.reason
			),
		)
		self.db_set("journal_entry", je.name, update_modified=False)

	def before_cancel(self):
		# The JE links back here; we cancel it ourselves in on_cancel.
		self.ignore_linked_doctypes = ("Journal Entry", "GL Entry", "Payment Ledger Entry")

	def on_cancel(self):
		cancel_journal_entry(self.journal_entry)

	def on_change(self):
		previous = previous_state(self)
		if not self.workflow_state or self.workflow_state == previous:
			return
		if self.workflow_state == STATE_PENDING_EXECUTIVE:
			notify(
				users_with_role(ROLE_EXECUTIVE),
				_("طلب تخصيص {0} من الصندوق العام لمشروع {1} بانتظار اعتمادك").format(
					sar(self.amount), self.to_project_title
				),
				self,
			)
		elif self.workflow_state == STATE_APPROVED and previous == STATE_PENDING_EXECUTIVE:
			notify([self.requested_by], _("تم اعتماد التخصيص {0}").format(self.name), self)
		elif self.workflow_state == STATE_REJECTED:
			notify(
				[self.requested_by],
				_("تم رفض التخصيص {0}: {1}").format(self.name, self.rejection_reason),
				self,
			)
