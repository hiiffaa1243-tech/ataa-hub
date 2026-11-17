"""Donor Payment Method: a saved card, as a Moyasar token only (PRD §5.2, §9.4).

- `moyasar_token` is a Password field: Frappe keeps it encrypted in __Auth and
  sends "*****" to any form or API, so the token never reaches a browser.
- The title is masked: "Visa •••• 1111 (12/28)".
- One default card per donor.
- Deleting the record deletes the token at Moyasar too.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

STATUS_ACTIVE = "Active"
STATUS_INACTIVE = "Inactive"
STATUS_DELETED = "Deleted"


class DonorPaymentMethod(Document):
	def validate(self):
		if self.last4 and (len(self.last4) != 4 or not self.last4.isdigit()):
			frappe.throw(_("آخر أربعة أرقام للبطاقة غير صحيحة."))
		if self.status != STATUS_ACTIVE:
			self.is_default = 0
		self.title = masked_title(self.brand, self.last4, self.expiry_month, self.expiry_year)

	def on_update(self):
		if self.is_default:
			# Only one default card per donor.
			frappe.db.sql(
				"""update `tabDonor Payment Method` set is_default = 0
				where customer = %s and name != %s and is_default = 1""",
				(self.customer, self.name),
			)

	def on_trash(self):
		if self.status != STATUS_DELETED:
			delete_token_at_moyasar(self)

	def token(self) -> str:
		"""The real token, for the server-side charge only."""
		return self.get_password("moyasar_token")

	def mark_deleted(self):
		"""Delete the token at Moyasar and keep the record (charge attempts link to it)."""
		delete_token_at_moyasar(self)
		self.status = STATUS_DELETED
		self.is_default = 0
		self.save(ignore_permissions=True)


def masked_title(brand, last4, month, year) -> str:
	brand = (brand or "card").replace("_", " ").title()
	expiry = f" ({cint(month):02d}/{cint(year) % 100:02d})" if month and year else ""
	return f"{brand} •••• {last4 or '????'}{expiry}"


def delete_token_at_moyasar(doc) -> None:
	from ataa_hub import moyasar

	try:
		moyasar.get_client().delete_token(doc.token())
	except moyasar.NotFound:
		pass  # already gone at Moyasar
	except Exception:
		# Never keep a donor's card alive silently: log it for the accountant.
		frappe.log_error(title=f"Moyasar: could not delete token of {doc.name}")


def get_default_method(customer: str) -> str | None:
	return frappe.db.get_value(
		"Donor Payment Method",
		{"customer": customer, "status": STATUS_ACTIVE},
		"name",
		order_by="is_default desc, creation desc",
	)
