"""ZATCA e-invoicing glue (PRD §7.11, D5).

Signing, clearance / reporting and the Phase-2 QR are done by the separate
`ksa_compliance` app (decided in M0); we never copy its code. Our part:

- `invoice_qr_text(doc)`: the QR shown on our Arabic membership invoice. If the
  ZATCA app produced a QR for the invoice we use it. Otherwise (e.g. CI, or a site
  not onboarded yet) we build the ZATCA *Phase-1* TLV QR (seller, VAT number,
  timestamp, total, VAT), so the print format always works.
- `setup_sandbox_demo()`: one explicit call for the demo site: fake tax data and a
  VAT template for membership invoices. Nothing here runs on install, so no tax
  position is hard-coded (Open question Q1).
"""

import base64

import frappe
from frappe.utils import flt, get_datetime

DEMO_VAT_NUMBER = "399999999900003"  # ZATCA's published sandbox test VAT number
DEMO_TEMPLATE_TITLE = "KSA VAT 15% Included"


def tlv(tag: int, value: str) -> bytes:
	data = str(value).encode("utf-8")
	if len(data) > 255:
		frappe.throw("ZATCA QR value too long")
	return bytes([tag, len(data)]) + data


def phase1_qr(seller: str, vat_number: str, timestamp, total, vat_total) -> str:
	"""Base64 TLV with ZATCA tags 1–5."""
	stamp = get_datetime(timestamp).strftime("%Y-%m-%dT%H:%M:%S")
	payload = (
		tlv(1, seller)
		+ tlv(2, vat_number)
		+ tlv(3, stamp)
		+ tlv(4, f"{flt(total):.2f}")
		+ tlv(5, f"{flt(vat_total):.2f}")
	)
	return base64.b64encode(payload).decode()


def decode_tlv(text: str) -> dict[int, str]:
	raw, out, i = base64.b64decode(text), {}, 0
	while i < len(raw):
		tag, length = raw[i], raw[i + 1]
		out[tag] = raw[i + 2 : i + 2 + length].decode("utf-8")
		i += 2 + length
	return out


def zatca_app_qr(invoice_name: str) -> str | None:
	"""QR produced by ksa_compliance, if that app is installed and has processed the invoice."""
	if "ksa_compliance" not in frappe.get_installed_apps():
		return None
	for doctype, field in (("Sales Invoice Additional Fields", "qr_code"),):
		if frappe.db.table_exists(doctype) and frappe.db.has_column(doctype, field):
			value = frappe.db.get_value(
				doctype,
				{"sales_invoice": invoice_name, field: ("is", "set")},
				field,
				order_by="creation desc",
			)
			if value:
				return value
	return None


def invoice_qr_text(doc) -> str:
	if doc.get("name") and (from_app := zatca_app_qr(doc.name)):
		return from_app
	company = frappe.get_cached_doc("Company", doc.company)
	return phase1_qr(
		company.company_name,
		company.tax_id or "",
		f"{doc.posting_date} {doc.get('posting_time') or '00:00:00'}",
		doc.grand_total,
		doc.total_taxes_and_charges,
	)


def setup_sandbox_demo(company: str | None = None) -> dict:
	"""Demo only: sandbox VAT number on the company and a VAT-inclusive membership template.

	VAT is *included* in the tier price, so a 50 SAR member still pays 50 SAR.
	"""
	from frappe.utils import cint

	company = company or frappe.db.get_single_value("Ataa Settings", "company")
	if not frappe.db.get_value("Company", company, "tax_id"):
		frappe.db.set_value("Company", company, "tax_id", DEMO_VAT_NUMBER)

	abbr = frappe.get_cached_value("Company", company, "abbr")
	template = f"{DEMO_TEMPLATE_TITLE} - {abbr}"
	if not frappe.db.exists("Sales Taxes and Charges Template", template):
		vat_account = _vat_account(company)
		frappe.get_doc(
			{
				"doctype": "Sales Taxes and Charges Template",
				"title": DEMO_TEMPLATE_TITLE,
				"company": company,
				"taxes": [
					{
						"charge_type": "On Net Total",
						"account_head": vat_account,
						"description": "VAT 15%",
						"rate": 15,
						"included_in_print_rate": 1,
						"cost_center": frappe.get_cached_value("Company", company, "cost_center"),
					}
				],
			}
		).insert(ignore_permissions=True)

	settings = frappe.get_single("Membership Settings")
	if not settings.sales_taxes_template:
		settings.sales_taxes_template = template
		settings.flags.ignore_permissions = True
		settings.flags.skip_tier_sync = True
		settings.save()
	return {
		"company": company,
		"tax_id": frappe.db.get_value("Company", company, "tax_id"),
		"template": template,
		"ok": cint(1),
	}


def _vat_account(company):
	account = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Tax", "is_group": 0, "account_name": ("like", "%VAT%")},
	) or frappe.db.get_value("Account", {"company": company, "account_type": "Tax", "is_group": 0})
	if account:
		return account
	parent = frappe.db.get_value(
		"Account", {"company": company, "account_name": "Duties and Taxes", "is_group": 1}
	) or frappe.db.get_value("Account", {"company": company, "root_type": "Liability", "is_group": 1})
	return (
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": "VAT 15%",
				"company": company,
				"parent_account": parent,
				"account_type": "Tax",
				"tax_rate": 15,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def zatca_invoice_qr(doc) -> str:
	"""Jinja name used by the Ataa Membership Invoice print format."""
	return invoice_qr_text(doc)
