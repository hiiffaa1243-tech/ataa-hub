import os

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
	"""Keys from the Moyasar Settings page, then site_config.json, then the environment
	(Codespaces secrets MOYASAR_PUBLISHABLE_KEY / MOYASAR_SECRET_KEY / MOYASAR_WEBHOOK_SECRET).

	The secret key is only ever read here on the server, never sent to a browser.
	"""
	settings = frappe.get_cached_doc("Moyasar Settings")

	def pick(stored, name):
		return stored or frappe.conf.get(name) or os.environ.get(name.upper()) or None

	return frappe._dict(
		publishable_key=pick(settings.publishable_key, "moyasar_publishable_key"),
		secret_key=pick(settings.get_password("secret_key", raise_exception=False), "moyasar_secret_key"),
		webhook_secret=pick(
			settings.get_password("webhook_secret", raise_exception=False), "moyasar_webhook_secret"
		),
	)
