import re

import frappe
from frappe import _
from frappe.model.document import Document

MOBILE_RE = re.compile(r"^\+9665\d{8}$")


class Donor(Document):
	def validate(self):
		self.mobile = (self.mobile or "").replace(" ", "")
		if not MOBILE_RE.match(self.mobile):
			frappe.throw(_("رقم الجوال يجب أن يكون بالصيغة +9665XXXXXXXX."))
		self.full_name = (self.full_name or "").strip()
