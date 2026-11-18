# Acceptance checklist (PRD §13)

Each criterion with the evidence for it. **Test** means an automated integration test that runs in CI on every push (162 tests, all green). **Demo** means it was checked on a fresh demo site (`setup.demo.seed` + `setup.demo.summary`, also run in CI). **Live** means it needs real external services and is marked with how far it was verified.

Status: ✅ verified · 🟡 verified in part (see note)

## Accounting

| | Criterion | Evidence |
|---|---|---|
| ✅ | Every submitted Donation has exactly one submitted JE with the project on both lines; cancelling the Donation cancels the JE | Test: `test_donation.test_submit_posts_one_journal_entry_with_project_on_both_lines`, `test_cancel_reverses_the_ledger`, `test_journal_entry_cannot_be_cancelled_on_its_own`; `test_api.test_create_posts_one_journal_entry_and_returns_201` |
| ✅ | Project balance on dashboard, API, portal and event screen equals the GL filtered by that project | One function reads the GL (`accounting.get_project_balance`) and every screen calls it. Test: `test_accounting.*` (8 tests), `test_reports.test_monthly_statement_agrees_with_the_gl`, `test_donations_this_month_is_gl_based`, `test_events.test_feed_totals` |
| ✅ | Restricted disbursement above the available balance is blocked at submit, approval and payment | Test: `test_spending.test_overspend_blocked_when_sent_for_review`, `test_blocked_at_executive_approval`, `test_blocked_at_payment_if_money_left`, `test_approved_money_is_committed_for_other_requests` |
| ✅ | Unrestricted money reaches a restricted project only through an approved Fund Allocation | Test: `test_spending.test_allocation_unblocks_a_restricted_request`, `test_only_unrestricted_to_restricted`, `test_cannot_allocate_more_than_general_available`, `test_checked_again_at_approval`; `test_donation.test_manual_journal_on_donation_income_needs_project` |

## API (v1 rules kept)

| | Criterion | Evidence |
|---|---|---|
| ✅ | Same request twice → one Donation, the second returns 200 `duplicate: true`; same reference with another amount → 409 | Test: `test_api.test_same_request_twice_is_recorded_once`, `test_reused_reference_with_different_values_is_409`, `test_idempotency_key_is_unique_in_the_database`; over HTTP: `test_api_http.test_valid_key_creates_posts_and_replays` |
| ✅ | Wrong key 401, inactive client 403, unknown project 404, inactive project 403 | Test: `test_api_http.test_wrong_key_is_401`, `test_missing_key_is_401`; `test_api.test_inactive_client_is_403`, `test_project_rules` |
| ✅ | `event_code` outside the window → 403 `EVENT_NOT_ACTIVE`; unknown terminal → 403 `TERMINAL_NOT_IN_EVENT` | Test: `test_api.test_unknown_closed_or_outside_window_is_event_not_active`, `test_unregistered_terminal`, `test_project_not_in_event` |

## Payments and memberships

| | Criterion | Evidence |
|---|---|---|
| ✅ | Changing the amount in the browser doesn't change what is recorded | Test: `test_payments.test_tampered_amount_is_never_recorded`, `test_memberships.test_wrong_amount_creates_nothing` |
| ✅ | Closing the browser after paying still records the donation (webhook) | Test: `test_payments.test_paid_payment_submits_once`, `test_webhook_rejects_wrong_secret`; plus the daily reconciliation heals a payment whose callback *and* webhook were lost: `test_reports.test_statuses_and_daily_healing` |
| ✅ | Sign-up stores an active token, creates Subscription + first invoice + Payment Entry | Test: `test_memberships.test_signup_builds_the_whole_membership`, `test_callback_twice_records_once` (Moyasar faked). Live token charge in test mode confirmed in M0 (PRD Q5) |
| ✅ | Daily job charges a due invoice and creates the Payment Entry; a failure schedules retries at +3 and +7 days and suspends after the third | Test: `test_memberships.test_due_invoice_is_charged_once`, `test_dunning_three_failures_then_suspended`, `test_not_due_yet_is_not_charged` |
| ✅ | A Processing attempt is never charged twice | Test: `test_memberships.test_timeout_stays_processing_and_is_never_recharged`, `test_reconciliation_finds_a_charge_that_did_go_through`, `test_unknown_result_goes_to_needs_review` |
| ✅ | Membership card values match the Subscription, latest Payment Entry and Donor Payment Method | Test: `test_portal.test_card_reads_live_sources`, `test_honorary_card_has_no_billing_fields` |

## Portal, events, receipts

| | Criterion | Evidence |
|---|---|---|
| ✅ | A donor sees only their own donations, invoices and cards | Test: `test_portal.test_list_rules_filter_by_donor`, `test_document_rules`, `test_portal_data_is_own_only`, `test_cannot_download_someone_elses_receipt`; `test_memberships.test_portal_methods_use_the_logged_in_donor` |
| 🟡 | Event screen updates without refresh when a terminal donation is submitted | Test: the feed is cleared on submit and the page polls it every 5 s (`test_events.test_cache_is_cleared_on_submit`, `test_cached_between_donations`, `test_guest_endpoint_and_disabled_screen`, `test_event_page_renders`). Demo: 7 POS donations show on `/event/CLOCKTOWER-2026`. The polling loop in the browser itself was not watched end to end |
| ✅ | Receipt QR opens a verification page with the correct number, date, amount and project | Test: `test_portal.test_receipt_print_has_qr_to_verify_page`, `test_verify_page_confirms_without_donor_data`, `test_cancelled_receipt_shows_as_cancelled` |
| 🟡 | Membership invoices are accepted by the ZATCA sandbox | Live: on a demo site with `ksa_compliance` 0.62 onboarded to the **Sandbox** Fatoora server (compliance + production CSID with the sandbox OTP), a membership invoice (50 SAR, VAT 6.52 included; tested before the tiers became annual) came back **Accepted with warnings**. The one warning, BR-KSA-08, asks for the seller's commercial registration number in ZATCA Business Settings. Our print format then showed ksa_compliance's 9-tag Phase-2 QR. Test: `test_reports.test_membership_invoice_with_vat_included`, `test_phase1_qr_round_trip` (CI has no ZATCA connection) |

## Governance

| | Criterion | Evidence |
|---|---|---|
| ✅ | A Project Manager cannot see other managers' projects or approve anything | Test: `test_donation.test_project_manager_sees_only_assigned_projects_and_their_donations`, `test_spending.test_project_manager_sees_only_own_requests`, `test_each_step_belongs_to_one_role` |
| ✅ | Every workflow transition is recorded with user and time | Track Changes is on for Disbursement Request, Fund Allocation and Donation (`test_spending.test_every_transition_is_recorded_with_user_and_time`). Frappe doesn't write versions inside tests, so `setup.demo.summary` prints the real trail of the paid demo request in CI: pm → accountant → ed → accountant, each with a timestamp |
| ✅ | Staff custody is paid only by the accountant, within the project's available balance, and closed only with an invoice on every purchase | `test_custody.test_full_cycle_books_the_money_and_attaches_a_report`, `test_cannot_pay_more_than_available`, `test_close_needs_an_invoice_on_every_line`, `test_only_the_accountant_pays_and_closes` |

## Success metrics (PRD §3)

| Goal | Target | Where it's shown |
|---|---|---|
| Time from payment to GL entry | < 5 s | The JE is posted inside the same request that verifies the payment (no queue) |
| Duplicate donations from the same external reference | 0 | Unique database index, `test_idempotency_key_is_unique_in_the_database` |
| Disbursements paid without a full approval trail | 0 | Workflow allows `Mark Paid` only from `Approved`; `test_each_step_belongs_to_one_role` |
| Restricted disbursements exceeding the project balance | 0 | Checks at every step with the project row locked |
| Balances that differ from the GL | 0 | Balances are never stored; all read from GL Entry |
| Due membership invoices charged by the daily job | 100 % of those with an active card | `charge_due_invoices`, `test_due_invoice_is_charged_once` |
| Membership invoices reported to the ZATCA sandbox | 100 % | 🟡 one invoice verified live (above); needs the seller CRN to clear the warning |
