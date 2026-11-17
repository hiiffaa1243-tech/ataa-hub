import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from ataa_hub.constants import PROJECT_ACTIVE
from ataa_hub.services import update_project_totals

PROJECT_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,29}$")


class DonationProject(Document):
	def before_insert(self):
		# The code becomes the document name, so normalise it before naming happens.
		self.project_code = (self.project_code or "").strip().upper()

	def validate(self):
		if not PROJECT_CODE_RE.match(self.project_code or ""):
			frappe.throw(
				_("رمز المشروع يجب أن يكون حروفاً إنجليزية كبيرة وأرقاماً وشرطة فقط، مثل SUQYA-01."),
				title=_("رمز غير صالح"),
			)

		if flt(self.target_amount) <= 0:
			frappe.throw(_("المبلغ المستهدف يجب أن يكون أكبر من صفر."))

		if not self.project_manager:
			self.project_manager = frappe.session.user

		for row in self.donation_options:
			if flt(row.amount) <= 0:
				frappe.throw(_("مبلغ الخيار «{0}» يجب أن يكون أكبر من صفر.").format(row.label))

		if self.status == PROJECT_ACTIVE and not self.allow_custom_amount and not self.donation_options:
			frappe.throw(_("المشروع النشط يحتاج خيار تبرع جاهز واحداً على الأقل، أو السماح بمبلغ حر."))

	def on_update(self):
		before = self.get_doc_before_save()
		if not before or flt(before.target_amount) != flt(self.target_amount):
			update_project_totals(self.name)
