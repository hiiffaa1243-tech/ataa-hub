import frappe
from frappe import _
from frappe.model.document import Document

from ataa_hub.constants import ROLE_API_CLIENT


class DonationAPIClient(Document):
	"""An external system (online store, POS terminal, partner platform) allowed to send donations.

	Each client gets its own machine user. That user's Frappe API key/secret is the
	"integration key" the store puts in the Authorization header. Unticking
	`is_active` blocks every request immediately, without touching the key.
	"""

	def validate(self):
		if not self.integration_user:
			self.integration_user = self.create_integration_user()
		else:
			self.ensure_api_role()

		seen = set()
		for row in self.allowed_projects:
			if row.project in seen:
				frappe.throw(_("المشروع {0} مكرر في قائمة المشاريع المسموحة.").format(row.project))
			seen.add(row.project)

	def create_integration_user(self) -> str:
		email = f"api-{frappe.generate_hash(length=10)}@integrations.ataa.test"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": self.client_name,
				"send_welcome_email": 0,
				"user_type": "Website User",
				"roles": [{"role": ROLE_API_CLIENT}],
			}
		)
		user.flags.ignore_permissions = True
		user.insert()
		return user.name

	def ensure_api_role(self):
		if ROLE_API_CLIENT not in frappe.get_roles(self.integration_user):
			user = frappe.get_doc("User", self.integration_user)
			user.add_roles(ROLE_API_CLIENT)

	@frappe.whitelist()
	def generate_keys(self):
		"""Create (or rotate) the key pair. The secret is shown once and stored encrypted."""
		frappe.only_for("System Manager")
		user = frappe.get_doc("User", self.integration_user)
		api_secret = frappe.generate_hash(length=15)
		if not user.api_key:
			user.api_key = frappe.generate_hash(length=15)
		user.api_secret = api_secret
		user.flags.ignore_permissions = True
		user.save()
		return {"api_key": user.api_key, "api_secret": api_secret}
