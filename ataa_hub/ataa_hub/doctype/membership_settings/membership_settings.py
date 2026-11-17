import frappe
from frappe import _
from frappe.model.document import Document


class MembershipSettings(Document):
	def validate(self):
		seen = set()
		for row in self.tiers:
			if row.tier in seen:
				frappe.throw(_("المستوى {0} مكرر.").format(row.tier))
			seen.add(row.tier)
			if row.monthly_amount <= 0:
				frappe.throw(_("مبلغ المستوى {0} يجب أن يكون أكبر من صفر.").format(row.tier))
		if self.first_retry_days < 1 or self.second_retry_days < 1:
			frappe.throw(_("أيام إعادة المحاولة يجب أن تكون يوماً واحداً على الأقل."))

	def on_update(self):
		# Keep Items / Subscription Plans in line with the amounts set here.
		from ataa_hub.setup.company import sync_membership_tiers

		if self.flags.skip_tier_sync:
			return

		sync_membership_tiers()
