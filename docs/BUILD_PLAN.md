# Ataa Hub v2 — Build Plan

Short plan to build [PRD.md v2](../PRD.md) and [API.md v2](../API.md). **No code is written until both documents are approved.** Each milestone ends in something demoable and a green test run.

## Starting point (v1 code already in the repo)

| Keep and adapt | Replace |
|---|---|
| API layer `api/v1.py`: error envelope, validation (all fields at once), auth checks, idempotency via unique index, race handling | `Donation Project` DocType → ERPNext **Project** + custom fields |
| Moyasar verification (`payments.py`): server-side fetch, webhook secret, callback + webhook once | `Donor` DocType → ERPNext **Customer** + Contact |
| `Donation API Client`, `Moyasar Settings` DocTypes | Stored balances (`collected_amount`, `spent_amount`) → GL-derived `get_project_balance` |
| Disbursement workflow states and row-lock balance checks | Disbursement "Disbursed" without accounting → **Paid** + Journal Entry |
| Test style (49 tests), Postman structure, Docker setup, CI, Arabic templates | v1 reports/number cards that read stored balances |

## Milestones

| # | Milestone | Main deliverables | Done when |
|---|---|---|---|
| **M0** | Spike (1 day, throwaway) | Docker bench with ERPNext **v16**; try installing `ksa_compliance`, then `zatca_erpgulf`; test guest realtime on a www page; one Moyasar test token charge (`3ds: false`); check Subscription invoice timing | Decisions D5, D6 and Q5 written into PRD §4.2 / §15. Fallback: v15 |
| **M1** | Foundation | App skeleton on ERPNext; `required_apps = ["erpnext"]`; fixtures (Custom Fields on Project / Customer / Sales Invoice / Payment Entry / Journal Entry, roles, Modes of Payment, Customer Group, Item Group); idempotent setup for accounts, GENERAL project, Items, Subscription Plans; Ataa / Membership / Moyasar Settings; `accounting.get_project_balance` | Fresh `install-app` builds everything; balance test passes |
| **M2** | Donations + GL | Donation DocType (submit → JE, cancel → reverse, impact frozen, idempotency key); Journal Entry `validate` project rule; donor = Customer matching; bank transfer flow; `/donate` + Moyasar page moved onto Draft/Submit | Every donation path posts exactly one JE; GL by project = API balance |
| **M3** | API v2 | `list_projects` new fields + event filter; `create_donation` submit in one transaction; `gift`; `event_code` checks; new errors; `get_donation` fields; openapi.yaml v2 + `/api-docs`; Postman v2 | All API tests + Postman run green |
| **M4** | Spending governance | Disbursement Request → Paid → JE; JE `on_cancel` returns it to Approved; Fund Allocation + Workflow + JE; restricted rules with row lock | Overspend blocked at every step; allocation enables a blocked request |
| **M5** | Memberships | Sign-up with `save_card` → Donor Payment Method → Subscription → first invoice + Payment Entry; daily charge job with Membership Charge Attempt; dunning (+3, +7, Suspended, notify Accountant); change tier / update card / cancel; monthly honorary job; Customer sync hooks | Charge, retry, suspend and "never charge twice" tests pass with a mocked Moyasar adapter |
| **M6** | Portal and public pages | `/my-giving` with membership card, donations, receipts, gifts, statement; permission query conditions for donors; `/gift/<token>`; `/verify/<token>`; Arabic print formats (receipt with QR, gift card, statement) | A donor sees only own data; QR opens verification page |
| **M7** | Events | Fundraising Event DocType; `/event/<event_code>` live screen with `publish_realtime` (+ polling fallback); demo `CLOCKTOWER-2026` with T01/T02 | Postman POS donation appears on the screen without refresh |
| **M8** | ZATCA + reports + dashboards | ZATCA app installed and onboarded to sandbox; membership invoice tax template from settings; 6 Script Reports; 3 workspaces with Number Cards (type Custom, GL-based); daily reconcile and monthly impact email jobs | Membership invoice accepted by sandbox; reports match the GL |
| **M9** | Polish and proof | Demo seed v2 (fake data); README v2; Arabic explainer `docs/شرح-المشروع.md` v2; CI with ERPNext; screenshots / short demo video; acceptance checklist (PRD §13) ticked | `docker compose up` → full 7-minute demo works from a clean machine |

## Test strategy

- Unit and integration tests with `FrappeTestCase` per milestone, run in CI against a real ERPNext site.
- External services behind adapters (`moyasar_client`, ZATCA calls): tests inject responses, no network.
- Accounting assertions always compare against **GL Entry**, not against our own fields.
- Postman collection is the end-to-end proof for the API.

## Order rationale

Accounting first (M1–M2), because every later feature (API, disbursements, memberships, reports) depends on "GL is the source of truth". Memberships (M5) come after governance because they are the largest and riskiest piece. ZATCA comes late because it depends on the M0 app choice and only touches membership invoices.

## Needs your decision before / during build

1. Approve PRD v2 and API v2.
2. Q3: honorary member who already pays (default: keep paying + Honorary badge).
3. Q6: confirm System Manager owns all settings (CR section 7 was truncated).
4. Q1: VAT position (default: donations out of scope, membership template configurable, demo 15 %).
