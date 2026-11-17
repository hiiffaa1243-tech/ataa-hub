"""doc_events on ERPNext's Journal Entry (no core change, PRD §9.1).

- validate: any line on a donation, membership, fund-transfer or program-expense
  account must carry a project. ERPNext's built-in `project` dimension is what
  makes restricted-fund balances possible (decision D1), so it can't be optional
  on these accounts, even for journals typed by hand.
- before_cancel: a journal created by one of our documents (Donation, later
  Disbursement Request / Fund Allocation) is cancelled through that document,
  so the two can never disagree.
"""

import frappe
from frappe import _

SETTINGS_ACCOUNT_FIELDS = (
	"restricted_income_account",
	"unrestricted_income_account",
	"fund_transfers_in_account",
	"fund_transfers_out_account",
	"disbursement_expense_account",
)


def project_required_accounts() -> set[str]:
	settings = frappe.get_cached_doc("Ataa Settings")
	accounts = {settings.get(f) for f in SETTINGS_ACCOUNT_FIELDS}
	accounts.add(frappe.db.get_single_value("Membership Settings", "membership_income_account"))
	accounts.discard(None)
	return accounts


def validate(doc, method=None):
	required = project_required_accounts()
	missing = [row.idx for row in doc.accounts if row.account in required and not row.project]
	if missing:
		frappe.throw(
			_("السطور {0}: الحسابات الخاصة بالتبرعات والصناديق تحتاج تحديد المشروع.").format(
				", ".join(map(str, missing))
			),
			title=_("المشروع مطلوب"),
		)


def before_cancel(doc, method=None):
	if doc.get("ataa_reference_doctype") and not doc.flags.from_ataa_document:
		frappe.throw(
			_("هذا القيد أُنشئ من {0} {1}. ألغي المستند الأصلي وسيُلغى القيد معه.").format(
				_(doc.ataa_reference_doctype), frappe.bold(doc.ataa_reference_name)
			),
			title=_("ألغي من المستند الأصلي"),
		)
