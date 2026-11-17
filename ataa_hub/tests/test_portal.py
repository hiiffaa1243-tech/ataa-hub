"""M6: donor portal, public gift / verify pages and print formats (PRD §7.6, §7.7, §8.2)."""

import shutil
import unittest
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, getdate, nowdate

from ataa_hub import memberships, permissions
from ataa_hub.donors import get_or_create_donor
from ataa_hub.portal import giving
from ataa_hub.public import gift_page, verify_page
from ataa_hub.tests.factories import make_bank_donation, make_project
from ataa_hub.tests.test_memberships import FakeMoyasar

HAS_PDF = bool(shutil.which("wkhtmltopdf"))


def make_donor(tag: str):
	"""Customer + Contact + portal user. Fake data only."""
	n = frappe.generate_hash(length=8)
	email = f"donor-{tag}-{n}@ataa.test"
	mobile = "+9665" + "".join(str(int(c, 16) % 10) for c in n)
	customer = get_or_create_donor(f"متبرع {tag}", mobile, email)
	memberships.ensure_portal_user(customer, email)
	return frappe._dict(customer=customer, email=email, mobile=mobile)


class PortalTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.project = make_project().name
		cls.a, cls.b = make_donor("a"), make_donor("b")
		cls.a_donation = make_bank_donation(cls.project, 120, donor=cls.a.customer).name
		cls.b_donation = make_bank_donation(cls.project, 300, donor=cls.b.customer).name

	def tearDown(self):
		frappe.set_user("Administrator")


class TestDonorSeesOwnData(PortalTestCase):
	def test_portal_user_is_linked_to_customer(self):
		self.assertEqual(giving.customers_for_user(self.a.email), [self.a.customer])
		self.assertTrue(permissions.is_portal_user(self.a.email))
		self.assertFalse(permissions.is_portal_user("Administrator"))

	def test_list_rules_filter_by_donor(self):
		condition = permissions.donation_query_conditions(self.a.email)
		names = frappe.db.sql_list(f"select name from `tabDonation` where {condition}")
		self.assertIn(self.a_donation, names)
		self.assertNotIn(self.b_donation, names)
		for fn in (
			permissions.sales_invoice_query_conditions,
			permissions.payment_entry_query_conditions,
			permissions.payment_method_query_conditions,
		):
			self.assertTrue(fn(self.a.email))
			self.assertEqual(fn("Administrator"), "")  # staff keep their normal access

	def test_document_rules(self):
		mine = frappe.get_doc("Donation", self.a_donation)
		theirs = frappe.get_doc("Donation", self.b_donation)
		self.assertTrue(permissions.donation_has_permission(mine, "read", self.a.email))
		self.assertFalse(permissions.donation_has_permission(theirs, "read", self.a.email))
		self.assertFalse(permissions.donation_has_permission(mine, "write", self.a.email))
		self.assertTrue(permissions.donation_has_permission(theirs, "read", "Administrator"))

	def test_portal_data_is_own_only(self):
		names = [r.name for r in giving.donations(self.a.customer)]
		self.assertEqual(names, [self.a_donation])
		impact = giving.impact_by_project(self.a.customer)
		self.assertEqual([flt(r.amount) for r in impact], [120])

	def test_cannot_download_someone_elses_receipt(self):
		frappe.set_user(self.a.email)
		with self.assertRaises(frappe.PermissionError):
			giving.download_receipt(self.b_donation)

	def test_download_own_receipt(self):
		frappe.set_user(self.a.email)
		with patch.object(giving, "render_print", return_value=b"%PDF-fake") as render:
			giving.download_receipt(self.a_donation)
		render.assert_called_once_with(self.a_donation, giving.RECEIPT_FORMAT, as_pdf=True)
		self.assertEqual(frappe.local.response.filename, f"receipt-{self.a_donation}.pdf")

	@unittest.skipUnless(HAS_PDF, "wkhtmltopdf not installed")
	def test_download_statement_pdf(self):
		frappe.set_user(self.a.email)
		giving.download_statement(getdate(nowdate()).year)
		self.assertTrue(frappe.local.response.filecontent.startswith(b"%PDF"))

	def test_my_giving_page(self):
		from frappe.utils import set_request
		from frappe.website.serve import get_response

		frappe.set_user(self.a.email)
		set_request(method="GET", path="/my-giving/donations")
		response = get_response()
		html = response.get_data(as_text=True)
		self.assertEqual(response.status_code, 200)
		self.assertIn(self.a_donation, html)
		self.assertNotIn(self.b_donation, html)

		frappe.set_user("Guest")
		set_request(method="GET", path="/my-giving")
		self.assertIn(get_response().status_code, (301, 302))


class TestPublicPages(PortalTestCase):
	def test_verify_page_confirms_without_donor_data(self):
		doc = frappe.get_doc("Donation", self.a_donation)
		page = verify_page(doc.receipt_token)
		self.assertEqual((page.receipt, page.valid, flt(page.amount)), (doc.name, True, 120))
		self.assertFalse({"donor", "donor_name", "donor_mobile", "donor_email"} & set(page))

		self.assertIsNone(verify_page("not-a-token"))
		self.assertIsNone(verify_page("A" * 32))

	def test_cancelled_receipt_shows_as_cancelled(self):
		doc = make_bank_donation(self.project, 50, donor=self.a.customer)
		doc.cancel_reason = "Duplicate"
		doc.save()
		doc.cancel()
		self.assertFalse(verify_page(doc.receipt_token).valid)

	def test_gift_page_hides_amount_unless_opted_in(self):
		gift = make_bank_donation(
			self.project,
			75,
			donor=self.a.customer,
			is_gift=1,
			recipient_name="سارة",
			recipient_email="sara@ataa.test",
			occasion="Eid",
			gift_message="عيدكم مبارك",
		)
		page = gift_page(gift.gift_token)
		self.assertEqual((page.recipient_name, page.occasion, page.amount), ("سارة", "Eid", None))
		self.assertFalse({"donor", "donor_name", "donor_mobile", "donor_email"} & set(page))

		gift.db_set("show_amount_on_gift", 1)
		self.assertEqual(gift_page(gift.gift_token).amount, 75)
		self.assertIsNone(gift_page(frappe.get_doc("Donation", self.a_donation).gift_token))

		self.assertEqual([r.name for r in giving.gifts(self.a.customer)], [gift.name])

	def test_receipt_print_has_qr_to_verify_page(self):
		doc = frappe.get_doc("Donation", self.a_donation)
		html = giving.render_print(doc.name, giving.RECEIPT_FORMAT)
		self.assertIn("data:image/png;base64,", html)
		self.assertIn(f"/verify/{doc.receipt_token}", html)
		self.assertIn(doc.project_title, html)


class TestMembershipCardAndStatement(PortalTestCase):
	def setUp(self):
		self.fake = FakeMoyasar()
		patcher = patch("ataa_hub.moyasar.get_client", return_value=self.fake)
		patcher.start()
		self.addCleanup(patcher.stop)
		ms = frappe.get_single("Moyasar Settings")
		ms.publishable_key, ms.secret_key = "pk_test_fake_publishable", "sk_test_fake_secret"
		ms.flags.ignore_permissions = True
		ms.save()

	def member(self):
		d = make_donor("m")
		form = memberships.start_signup_for("Bronze", "عضو", d.email, d.mobile)
		pid = self.fake.signup_payment(form["intent"], form["amount_halalas"])
		result = memberships.complete_signup(pid)
		self.assertTrue(result.ok, result.reason)
		return d, result

	def test_card_reads_live_sources(self):
		d, r = self.member()
		card = giving.membership_card(d.customer)
		sub = frappe.get_doc("Subscription", r.subscription)
		self.assertEqual(
			(card.tier, card.status, card.label, card.live), ("Bronze", "Active", "برونزي", True)
		)
		self.assertEqual(flt(card.last_charge.paid_amount), 50)
		self.assertEqual(getdate(card.next_charge), getdate(sub.current_invoice_start))
		self.assertEqual(card.payment_method, "Visa •••• 1111 (12/30)")
		self.assertNotIn("Bronze", [t.tier for t in card.tiers])

	def test_honorary_card_has_no_billing_fields(self):
		d, _r = self.member()
		memberships.grant_honorary_to(d.customer)
		card = giving.membership_card(d.customer)
		self.assertTrue(card.honorary)
		self.assertEqual(str(card.honorary_since), nowdate())
		self.assertNotIn("last_charge", card)
		self.assertNotIn("payment_method", card)

	def test_annual_statement_totals(self):
		d, _r = self.member()
		make_bank_donation(self.project, 200, donor=d.customer)
		s = giving.statement(d.customer, getdate(nowdate()).year)
		self.assertEqual((flt(s.total_donations), flt(s.total_memberships), flt(s.total)), (200, 50, 250))
		html = giving.render_statement(s)
		self.assertIn("كشف العطاء السنوي", html)
		self.assertEqual(giving.statement(d.customer, 2001).total, 0)
