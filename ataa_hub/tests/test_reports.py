"""M8: Script Reports, reconciliation, dashboards, impact email and ZATCA glue (PRD §7.11, §9.2, §10)."""

import base64
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, add_to_date, flt, now_datetime, nowdate

from ataa_hub import dashboards, impact, memberships, payments, reconciliation, zatca
from ataa_hub.accounting import get_project_balance
from ataa_hub.constants import ROLE_PROFILES
from ataa_hub.tests.factories import (
	make_api_client,
	make_bank_donation,
	make_event,
	make_integration_donation,
	make_journal_entry,
	make_project,
	make_user,
	settings,
	unique,
)
from ataa_hub.tests.test_memberships import FakeMoyasar
from ataa_hub.tests.test_payments import fake_payment

ED = "ed-reports@ataa.test"


def run_report(name, **filters):
	from frappe.desk.query_report import run

	result = run(name, filters=filters, ignore_prepared_report=True)
	return result["columns"], result["result"]


class ReportsTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(ED, ROLE_PROFILES["Ataa Executive Director"])
		ms = frappe.get_single("Moyasar Settings")
		ms.publishable_key, ms.secret_key = "pk_test_fake_publishable", "sk_test_fake_secret"
		ms.flags.ignore_permissions = True
		ms.save()

	def tearDown(self):
		frappe.set_user("Administrator")


class TestReports(ReportsTestCase):
	def test_donations_by_project_and_channel(self):
		project = make_project().name
		make_bank_donation(project, 100)
		make_bank_donation(project, 50)
		make_integration_donation(project, 30)
		_cols, rows = run_report("Donations by Project and Channel", project=project)
		got = {(r["channel"], r["count"], flt(r["amount"])) for r in rows}
		self.assertEqual(got, {("Bank Transfer", 2, 150), ("Online Store", 1, 30)})

	def test_monthly_statement_agrees_with_the_gl(self):
		project = make_project().name
		make_bank_donation(project, 1000)
		make_journal_entry(
			[
				(settings().disbursement_expense_account, 300, 0, project),
				(settings().main_bank_account, 0, 300, project),
			]
		)
		_cols, rows = run_report(
			"Monthly Project Statement", project=project, from_date=add_days(nowdate(), -1), to_date=nowdate()
		)
		[row] = rows
		self.assertEqual((flt(row["donations"]), flt(row["expenses"]), flt(row["opening"])), (1000, 300, 0))
		self.assertEqual(flt(row["closing"]), get_project_balance(project).balance)

		# Next period: the balance becomes the opening balance
		_cols, [later] = run_report(
			"Monthly Project Statement",
			project=project,
			from_date=add_days(nowdate(), 1),
			to_date=add_days(nowdate(), 30),
		)
		self.assertEqual((flt(later["opening"]), flt(later["closing"])), (700, 700))

	def test_impact_report(self):
		project = make_project(impact_unit_label="وجبة", impact_units_per_sar=0.5).name
		make_bank_donation(project, 100)
		_cols, rows = run_report("Impact Report", project=project)
		self.assertEqual([(flt(r["impact_units"]), r["impact_unit_label"]) for r in rows], [(50, "وجبة")])

	def test_event_performance(self):
		project = make_project().name
		pos = make_api_client(unique("POS"), "POS", allowed=[project]).name
		event = make_event(projects=[project], terminals=[(pos, "T01"), (pos, "T02")])
		for terminal, amount, scheme in (("T01", 100, "mada"), ("T01", 50, "visa"), ("T02", 20, "mada")):
			make_integration_donation(
				project,
				amount,
				channel="POS",
				api_client=pos,
				fundraising_event=event.name,
				terminal_id=terminal,
				card_scheme=scheme,
				rrn=unique("RRN"),
				paid_at=add_to_date(now_datetime(), minutes=-5),
			)
		_c, by_terminal = run_report("Event Performance", event=event.name, group_by="Terminal")
		self.assertEqual({r["bucket"]: flt(r["amount"]) for r in by_terminal}, {"T01": 150, "T02": 20})
		_c, by_scheme = run_report("Event Performance", event=event.name, group_by="Card Scheme")
		self.assertEqual({r["bucket"]: r["count"] for r in by_scheme}, {"mada": 2, "visa": 1})
		_c, by_hour = run_report("Event Performance", event=event.name, group_by="Hour")
		self.assertEqual(sum(r["count"] for r in by_hour), 3)

	def test_membership_report_and_cards(self):
		fake = FakeMoyasar()
		with patch("ataa_hub.moyasar.get_client", return_value=fake):
			n = frappe.generate_hash(length=8)
			form = memberships.start_signup_for(
				"Gold", "عضو تقرير", f"rep-{n}@ataa.test", "+9665" + "".join(str(int(c, 16) % 10) for c in n)
			)
			self.assertTrue(
				memberships.complete_signup(fake.signup_payment(form["intent"], form["amount_halalas"])).ok
			)

		_c, rows = run_report("Membership Report")
		gold = next(r for r in rows if r["tier"] == "Gold")
		self.assertGreaterEqual(gold["active"], 1)
		self.assertGreaterEqual(gold["new"], 1)
		self.assertEqual(flt(gold["mrr"]), (gold["active"] + gold["payment_pending"]) * 250)

		frappe.set_user(ED)
		self.assertGreaterEqual(dashboards.active_members()["value"], 1)
		self.assertGreaterEqual(dashboards.monthly_recurring_revenue()["value"], 250)


class TestReconciliation(ReportsTestCase):
	def website_donation(self, amount=100):
		code = unique("REC")
		make_project(code=code, allow_custom_amount=1)
		return payments.create_pending_donation_for(code, amount)["donation_id"]

	def test_statuses_and_daily_healing(self):
		matched_id = self.website_donation(100)
		pid_ok, pay_ok = fake_payment(matched_id, 10000)
		payments.verify_and_record_payment(pid_ok, pay_ok)

		lost_id = self.website_donation(70)  # callback and webhook both lost
		pid_lost, pay_lost = fake_payment(lost_id, 7000)

		ours_only = self.website_donation(40)
		pid_ours, pay_ours = fake_payment(ours_only, 4000)
		payments.verify_and_record_payment(pid_ours, pay_ours)  # Moyasar won't list it

		stamp = now_datetime().strftime("%Y-%m-%dT%H:%M:%S.000Z")
		listed = [dict(p, created_at=stamp) for p in (pay_ok, pay_lost)]
		listed.append(
			{
				"id": "00000000-0000-0000-0000-000000000000",
				"status": "paid",
				"amount": 999,
				"created_at": stamp,
			}
		)

		rows = {r["payment_id"]: r["status"] for r in reconciliation.reconcile(nowdate(), nowdate(), listed)}
		self.assertEqual(rows[pid_ok], reconciliation.MATCHED)
		self.assertEqual(rows[pid_lost], reconciliation.MISSING_HERE)
		self.assertEqual(rows[pid_ours], reconciliation.MISSING_THERE)

		summary = reconciliation.run_daily(today=nowdate(), payments=listed)
		self.assertEqual(summary["healed"], [pid_lost])
		self.assertEqual(frappe.db.get_value("Donation", lost_id, "docstatus"), 1)
		self.assertEqual(
			frappe.db.get_single_value("Moyasar Settings", "reconciliation_issues"), len(summary["issues"])
		)
		statuses = {i["payment_id"]: i["status"] for i in summary["issues"]}
		self.assertNotIn(pid_lost, statuses)  # healed
		self.assertEqual(statuses["00000000-0000-0000-0000-000000000000"], reconciliation.MISSING_HERE)

		with patch.object(reconciliation, "list_moyasar_payments", return_value=listed):
			_c, report_rows = run_report(
				"Moyasar Reconciliation", from_date=nowdate(), to_date=nowdate(), only_issues=1
			)
		self.assertNotIn(pid_ok, [r["payment_id"] for r in report_rows])

	def test_amount_mismatch(self):
		donation = self.website_donation(100)
		pid, pay = fake_payment(donation, 10000)
		payments.verify_and_record_payment(pid, pay)
		listed = [dict(pay, amount=9000, created_at=nowdate() + "T10:00:00Z")]
		[row] = [r for r in reconciliation.reconcile(nowdate(), nowdate(), listed) if r["payment_id"] == pid]
		self.assertEqual(row["status"], reconciliation.AMOUNT_MISMATCH)


class TestDashboardsAndJobs(ReportsTestCase):
	def test_number_cards_and_workspaces_are_installed(self):
		self.assertEqual(frappe.db.count("Number Card", {"module": "Ataa Hub"}), len(dashboards.CARDS))
		for ws in ("Ataa Executive", "Ataa Project Manager", "Ataa Accountant"):
			self.assertTrue(frappe.db.exists("Workspace", ws), ws)

	def test_every_card_method_answers(self):
		frappe.set_user(ED)
		for _label, method, _colour in dashboards.CARDS.values():
			result = getattr(dashboards, method)()
			self.assertIn("value", result, method)

	def test_cards_are_staff_only(self):
		donor = f"donor-cards-{frappe.generate_hash(length=6)}@ataa.test"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": donor,
				"first_name": "Donor",
				"user_type": "Website User",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		frappe.set_user(donor)
		with self.assertRaises(frappe.PermissionError):
			dashboards.donations_this_month()

	def test_donations_this_month_is_gl_based(self):
		frappe.set_user(ED)
		before = dashboards.donations_this_month()["value"]
		frappe.set_user("Administrator")
		make_bank_donation(make_project().name, 123)
		frappe.set_user(ED)
		self.assertEqual(flt(dashboards.donations_this_month()["value"] - before), 123)

	def test_monthly_impact_email(self):
		fake = FakeMoyasar()
		with patch("ataa_hub.moyasar.get_client", return_value=fake):
			n = frappe.generate_hash(length=8)
			form = memberships.start_signup_for(
				"Bronze", "عضو أثر", f"imp-{n}@ataa.test", "+9665" + "".join(str(int(c, 16) % 10) for c in n)
			)
			memberships.complete_signup(fake.signup_payment(form["intent"], form["amount_halalas"]))
		make_bank_donation(make_project(impact_unit_label="وجبة", impact_units_per_sar=1).name, 80)
		with patch("frappe.sendmail") as sendmail:
			sent = impact.send_monthly_impact_emails(today=add_months(nowdate(), 1))
		self.assertGreaterEqual(sent, 1)
		recipients = [c.kwargs["recipients"][0] for c in sendmail.call_args_list]
		self.assertIn(f"imp-{n}@ataa.test", recipients)


class TestZatca(ReportsTestCase):
	def test_phase1_qr_round_trip(self):
		text = zatca.phase1_qr("جمعية عطاء", "399999999900003", "2026-11-19 10:30:00", 57.5, 7.5)
		self.assertEqual(
			zatca.decode_tlv(text),
			{1: "جمعية عطاء", 2: "399999999900003", 3: "2026-11-19T10:30:00", 4: "57.50", 5: "7.50"},
		)
		# Phase-2 QRs (from ksa_compliance) add binary tags: kept as base64, never a decode error
		phase2 = base64.b64decode(text) + bytes([6, 3, 0x86, 0xFF, 0x00])
		self.assertEqual(zatca.decode_tlv(base64.b64encode(phase2).decode())[6], "hv8A")

	def test_membership_invoice_with_vat_included(self):
		result = zatca.setup_sandbox_demo()
		self.assertEqual(result["tax_id"], frappe.db.get_value("Company", result["company"], "tax_id"))
		# ksa_compliance reads the ZATCA category from the template's Tax Category
		self.assertEqual(
			frappe.db.get_value("Sales Taxes and Charges Template", result["template"], "tax_category"),
			zatca.DEMO_TAX_CATEGORY,
		)

		fake = FakeMoyasar()
		with patch("ataa_hub.moyasar.get_client", return_value=fake):
			n = frappe.generate_hash(length=8)
			form = memberships.start_signup_for(
				"Bronze",
				"عضو ضريبة",
				f"vat-{n}@ataa.test",
				"+9665" + "".join(str(int(c, 16) % 10) for c in n),
			)
			r = memberships.complete_signup(fake.signup_payment(form["intent"], form["amount_halalas"]))
		inv = frappe.get_doc("Sales Invoice", r.invoice)
		# VAT included in the tier price: the member still pays 50, of which VAT is 6.52
		self.assertEqual(flt(inv.grand_total), 50)
		self.assertEqual(flt(inv.total_taxes_and_charges), 6.52)
		self.assertEqual(flt(inv.outstanding_amount), 0)

		qr = zatca.decode_tlv(zatca.invoice_qr_text(inv))
		self.assertEqual((qr[2], qr[4], qr[5]), (result["tax_id"], "50.00", "6.52"))
		html = frappe.get_print("Sales Invoice", inv.name, "Ataa Membership Invoice")
		self.assertIn("فاتورة ضريبية مبسطة", html)
		self.assertIn("data:image/png;base64,", html)
