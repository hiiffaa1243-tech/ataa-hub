import frappe
from frappe import _
from frappe.model.document import Document


class MoyasarSettings(Document):
	def validate(self):
		# Version 1.0 runs on Moyasar's test environment only (PRD section 9).
		if self.publishable_key and not self.publishable_key.startswith("pk_test_"):
			frappe.throw(_("المفتاح العام يجب أن يبدأ بـ pk_test_ (بيئة الاختبار فقط)."))

		secret = self.secret_key
		# Password fields come back masked ("*****") when unchanged; only check new values.
		if secret and not set(secret) <= {"*"} and not secret.startswith("sk_test_"):
			frappe.throw(_("المفتاح السري يجب أن يبدأ بـ sk_test_ (بيئة الاختبار فقط)."))


def get_moyasar_config() -> frappe._dict:
	"""Keys from the Moyasar Settings page, falling back to site_config.json.

	The secret key is only ever read here on the server, never sent to a browser.
	"""
	settings = frappe.get_cached_doc("Moyasar Settings")
	return frappe._dict(
		publishable_key=settings.publishable_key or frappe.conf.get("moyasar_publishable_key"),
		secret_key=settings.get_password("secret_key", raise_exception=False)
		or frappe.conf.get("moyasar_secret_key"),
		webhook_secret=settings.get_password("webhook_secret", raise_exception=False)
		or frappe.conf.get("moyasar_webhook_secret"),
	)
