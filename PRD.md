# Ataa Hub — Product Requirements Document v2
### A custom Frappe app on top of ERPNext for nonprofit donations, memberships and governed spending

| Item | Value |
|---|---|
| Version | **2.0 (draft for approval)** — supersedes v1 ([archive](docs/archive/v1/PRD-v1.md)) |
| Owner | هيفاء عبدالرزاق |
| Type | Portfolio project, fake data only |
| Stack | ERPNext + Frappe Framework, Python, JavaScript, MariaDB, Redis |
| App name | `ataa_hub`, installed next to `erpnext` on the same site |
| Payment gateway | Moyasar, **test mode only** |
| E-invoicing | ZATCA, **sandbox only** |
| Companion docs | [API.md](API.md) (integration contract) · [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md) |

---

## 1. Problem

In many Saudi associations the donation cycle is manual and invisible:

- The online store sends donations as **monthly Excel files**, one per project, matched by hand in accounting.
- **Project managers** don't know their project's real available balance, so disbursement requests are late or wrong.
- The **executive director** waits for the monthly report and approves spending over WhatsApp or paper, with no audit trail.
- The **accountant** reconciles bank, store, POS terminals and the gateway by hand.
- **Recurring supporters** (monthly members) are billed manually, and failed payments are chased by phone.
- Restricted gifts and general donations are mixed, which is a governance risk with regulators.

## 2. Solution

A custom app on **ERPNext** that:

1. Receives donations **in real time** from every channel (donation page, online stores, POS terminals at events, bank transfers) and books each one to the **General Ledger** against its project.
2. Runs **monthly memberships** on native ERPNext Subscriptions, with automatic card charging and dunning.
3. Separates **restricted and unrestricted funds** in the books and blocks overspending of restricted money.
4. Runs disbursements through an **audited approval workflow** that ends in a Journal Entry.
5. Gives each role a dashboard and gives donors a **portal** (membership card, impact, receipts, statements).
6. Issues **ZATCA-compliant e-invoices** for memberships and **verifiable receipts** for donations.

**Interview line:** "Instead of building a parallel system, I extended ERPNext: donors are Customers, projects are Projects, every riyal is a GL entry tagged with its project, memberships are native Subscriptions. My app adds what ERPNext doesn't have: a donation document, a public API with idempotency, card tokenization and dunning, fund rules, and an approval workflow."

## 3. Goals and success metrics (demo targets)

| Goal | Metric | Target |
|---|---|---|
| End monthly Excel reconciliation | Time from payment to GL entry | < 5 s |
| No duplicates | Duplicate donations from the same external reference | 0 |
| Governed spending | Disbursements paid without full approval trail | 0 |
| Restricted-fund integrity | Restricted disbursements exceeding project balance | 0 |
| Single source of truth | Balances shown anywhere that differ from the GL | 0 |
| Reliable memberships | Due membership invoices charged automatically by the daily job | 100 % of those with an active card |
| Compliance | Membership invoices reported to ZATCA sandbox | 100 % |

---

## 4. Architecture principles and key decisions

### 4.1 Principles (from the change request — non-negotiable)

1. `ataa_hub` is installed **alongside** `erpnext`. ERPNext and Frappe core are **never** modified.
2. Behaviour changes only through `hooks.py` (`doc_events`, `scheduler_events`, `override_whitelisted_methods` only if unavoidable), Custom Fields, Property Setters and our own DocTypes.
3. Reuse a native ERPNext DocType whenever one exists; create a custom DocType only when there is no equivalent.
4. All customizations ship as **fixtures** so `bench install-app ataa_hub` on a fresh site gives everything.
5. **The General Ledger is the single source of truth for money.** Balances are derived from GL Entries, never stored as a manually maintained number.
6. Arabic RTL UI, English technical docs, fake data only, no secrets in the repo.

### 4.2 Decisions taken in this document

| # | Decision | Why |
|---|---|---|
| D1 | **Use ERPNext's native `project` dimension on GL Entry**, not a new Accounting Dimension "Donation Project". | ERPNext **blocks** creating an Accounting Dimension whose document type is Project (`accounting_dimension.py → validate_doctype`), because `project` (with `cost_center`) is already a built-in dimension on GL Entry, Journal Entry Account, Sales Invoice and Payment Entry. Using it gives the same result with zero extra schema, and native reports (General Ledger, Profit and Loss, Project-wise reports) already filter by it. "Mandatory project" is enforced by our hooks (see 9.1), because the native mandatory-dimension settings apply only to custom dimensions. |
| D2 | **Project balance = net P&L of that project in the GL.** | Income accounts (donations, fund transfers in) add, expense accounts (disbursements, fund transfers out) subtract. One SQL over GL Entry (`is_cancelled = 0`, `project = P`, P&L accounts) gives the balance, so it can never drift. |
| D3 | **Fund Allocation is a small custom submittable DocType with its own Workflow**, which posts a Journal Entry on approval. | A Workflow on Journal Entry would apply to *every* journal in the company (payroll, depreciation, manual corrections) and break normal accounting. A dedicated document keeps the approval scoped, carries its own validation (enough unrestricted balance) and links to the JE it created. |
| D4 | **Fund transfers use two income-type accounts**, "Fund Transfers Out" (debit, project GENERAL) and "Fund Transfers In" (credit, target project). | They net to zero at company level, but per project they move the balance, so D2 still holds. |
| D5 | **ZATCA: integrate an existing open-source app**; first candidate `ksa_compliance` (LavaLoon), fallback `zatca_erpgulf` (ERPGulf). Final choice after a one-day spike (Build Plan, M0). | Both are open source and used in production. `ksa_compliance` lists simplified (B2C) invoices and ZATCA sandbox support, which matches our need. It is AGPL-3.0: acceptable because it is installed as a separate app, not copied into ours. `zatca_erpgulf` is MIT but its README lists standard invoices / credit / debit notes and ERPNext 13–15. Building ZATCA signing from scratch is out of scope. |
| D6 | **ERPNext version: v16 if the chosen ZATCA app installs cleanly on it, else v15.** Decided in the M0 spike. | v16 is the current stable line (released January 2026). ZATCA app compatibility is the deciding constraint. Everything in this PRD exists in both versions. |
| D7 | **Pending website donations are Draft Donations.** Submit = money received. Cancel = reversal / refund. | Uses Frappe's native docstatus life cycle instead of a custom status machine. The GL posting happens exactly once, on submit. |
| D8 | **A membership charge attempt is logged in a custom DocType** "Membership Charge Attempt". | Dunning needs a record per attempt (when, result, next retry, Moyasar id), and it protects against double charging. ERPNext has no equivalent. |

### 4.3 What we add vs. what we reuse

| Our concept | ERPNext object | How we extend it |
|---|---|---|
| Donation project | **Project** (native) | Custom fields (5.1) |
| Project in accounting | **`project` dimension** on GL Entry (native) | Mandatory on every donation, membership and disbursement entry (D1) |
| General / unrestricted fund | Project **GENERAL** (fund_type = Unrestricted) | Created by fixtures/setup |
| Donor | **Customer** (native), Customer Group "Donors" | Custom fields (5.1) |
| Donor contact & login | **Contact** + Website **User** (native portal) | Created on first identified donation or membership |
| One-off donation | **Donation** (new, submittable) | Posts a Journal Entry on submit (no native donation document; the official Non Profit app is archived) |
| Donation accounting | **Journal Entry** (native) | Created and cancelled by the Donation controller |
| Payment methods | **Mode of Payment** (native) | mada POS, Bank Transfer, Moyasar Online, Online Store, Partner |
| Membership tiers | **Item** + **Subscription Plan** (native), one per paid tier | Monthly |
| Membership | **Subscription** (native) | Generates monthly Sales Invoices; we add card charging and dunning |
| Membership payment | **Sales Invoice** + **Payment Entry** (native) | Payment Entry auto-created after a successful token charge |
| Saved card | **Donor Payment Method** (new) | Moyasar token only, never card data |
| Charge attempts | **Membership Charge Attempt** (new) | D8 |
| Disbursement | **Disbursement Request** (new) + Workflow | Posts a Journal Entry when paid |
| Unrestricted → restricted | **Fund Allocation** (new) + Workflow | Posts a Journal Entry when approved (D3) |
| API channels | **Donation API Client** (new) | Linked to an integration User with API key/secret |
| Fundraising event | **Fundraising Event** (new) | Projects and terminals, live screen |
| E-invoicing | ZATCA app (third-party, D5) | Our setup: company tax data, tax template, sandbox onboarding |
| Reports | General Ledger, Profit and Loss (native, filtered by project) + 6 Script Reports | |

---

## 5. Data model

### 5.1 Custom fields on native DocTypes (shipped as fixtures)

**Project**

| Field | Type | Notes |
|---|---|---|
| `fund_type` | Select: Restricted / Unrestricted | Required. GENERAL is the only Unrestricted project by default |
| `target_amount` | Currency | > 0 for Restricted projects |
| `is_public` | Check | Shown on the donation page and API |
| `public_title` | Data | Arabic title for donors (Project name stays internal) |
| `public_description` | Small Text | |
| `public_image` | Attach Image | |
| `impact_unit_label` | Data | e.g. "معتمر سُقي" (pilgrims given water) |
| `impact_units_per_sar` | Float | e.g. 1.0 |
| `allow_custom_amount` | Check | |
| `donation_options` | Table → **Project Donation Option** (new child: label, amount) | Ready-made amounts |
| `project_code` | Data, unique | Stable code used by the API (e.g. `SUQYA-01`); the Project `name` stays ERPNext's own |

Property Setters: none required on Project. Native `project_name`, `status` (Open / Completed / Cancelled), `is_active` and `company` are reused. **A project accepts donations only when `status = Open`, `is_active = Yes` and `is_public = 1`.**

**Customer** (Customer Group "Donors")

| Field | Type | Notes |
|---|---|---|
| `donor_mobile` | Data, unique | `+9665XXXXXXXX`, used to match returning donors |
| `membership_tier` | Select: — / Bronze / Silver / Gold / Platinum / Honorary | Read-only, synced by hooks |
| `membership_status` | Select: — / Active / Payment Pending / Suspended / Cancelled | Read-only, synced by hooks |
| `membership_subscription` | Link → Subscription | Read-only, the current membership Subscription |
| `member_since` | Date | Read-only |
| `honorary_since` | Date | Read-only |
| `lifetime_giving` | Currency | Read-only cache, **recomputed from source documents** (submitted Donations + paid membership invoices), never incremented |

**Sales Invoice / Payment Entry**: `is_membership` (Check, read-only) so hooks, reports and the portal can find membership documents without guessing. Journal Entry: `ataa_reference_doctype` / `ataa_reference_name` (read-only) back-links to the Donation, Disbursement Request or Fund Allocation that created it.

### 5.2 New DocTypes

**Donation** (submittable, naming `DON-.YYYY.-.#####`, Track Changes)

| Field | Type | Notes |
|---|---|---|
| `company` | Link Company | Default company |
| `project` | Link Project | Required, must accept donations |
| `fund_type` | Data (fetched) | From project |
| `amount` | Currency | > 0, SAR |
| `posting_date` / `paid_at` | Date / Datetime | `paid_at` from the channel |
| `channel` | Select: Website / Online Store / POS / Bank Transfer / Partner | Set from the API Client for API donations |
| `mode_of_payment` | Link Mode of Payment | Decides the debit account |
| `donor` | Link Customer | Optional (anonymous allowed) |
| `donor_name`, `donor_mobile`, `donor_email` | Data | As received |
| `api_client`, `external_reference` | Link / Data | API donations |
| `idempotency_key` | Data, **unique**, read-only | `<api_client>:<external_reference>`, or `moyasar:<payment_id>` for website donations |
| `payment_reference` | Data | Gateway id, terminal auth code, or bank reference |
| `terminal_id`, `card_scheme`, `rrn` | Data | POS only, all required for POS |
| `fundraising_event` | Link Fundraising Event | Optional |
| `impact_units`, `impact_unit_label` | Float / Data | Frozen at submit: amount × rate at that moment |
| `is_gift` + `recipient_name`, `recipient_mobile`, `recipient_email`, `occasion`, `gift_message` | | Gift donations (7.6) |
| `gift_token`, `receipt_token` | Data, unique, hidden | Unguessable tokens for public gift and verification pages |
| `transfer_proof` | Attach | Required to submit a Bank Transfer |
| `payment_status` | Select: Awaiting Payment / Paid / Failed / Refunded | Website flow on Draft; set to Paid on submit, Refunded on cancel |
| `journal_entry` | Link Journal Entry | Read-only |
| `cancel_reason` | Small Text | Required to cancel |
| `raw_payload` | Code (JSON) | **permlevel 1**: System Manager and Accountant only |

**Disbursement Request** (submittable, `DSB-.YYYY.-.#####`, Workflow 7.8)

`company`, `project`, `fund_type` (fetched), `amount`, `purpose`, `expense_account` (Link Account, expense, default from settings), `paid_from_account` (Link Account, bank/cash), `supplier` (optional Link Supplier), `attachments`, `requested_by`, `available_balance_at_request` (snapshot), `accountant_notes`, `rejection_reason`, `journal_entry` (read-only), `paid_on` (read-only), `workflow_state`.

**Fund Allocation** (submittable, `FAL-.YYYY.-.#####`, Workflow 7.9)

`company`, `from_project` (default GENERAL, must be Unrestricted), `to_project` (must be Restricted), `amount`, `reason`, `journal_entry` (read-only), `workflow_state`.

**Donor Payment Method** (`DPM-.#####`)

`customer`, `moyasar_token` (**Password**, never sent to a browser or API response), `brand`, `last4`, `expiry_month`, `expiry_year`, `status` (Active / Inactive / Deleted), `is_default`, `source_payment_id`. Title shows `Visa •••• 1111 (12/28)`. Visible to the Accountant (masked) and to the owning donor in the portal (masked).

**Membership Charge Attempt** (`MCA-.YYYY.-.#####`)

`sales_invoice`, `customer`, `payment_method`, `attempt_no` (1–3), `status` (Processing / Succeeded / Failed / Needs Review), `amount`, `moyasar_payment_id`, `error_message`, `next_retry_on`, `payment_entry`.

**Donation API Client** (as v1)

`client_name`, `channel` (Online Store / POS / Partner), `integration_user` (auto-created, key/secret generated from the form), `allowed_projects` (Table MultiSelect), `is_active`, `last_request_on`.

**Fundraising Event** (named by `event_code`, e.g. `CLOCKTOWER-2026`)

`event_name` ("Clock Tower Booth – Makkah"), `location`, `start_datetime`, `end_datetime`, `target_amount`, `status` (Planned / Active / Closed), `projects` (child: project), `terminals` (child: api_client, terminal_id, label — e.g. T01-CLOCKTOWER, T02-CLOCKTOWER), `live_screen_enabled`.

**Settings (Single DocTypes)**

- **Ataa Settings**: default company, income accounts (Restricted / Unrestricted Donations Income), fund transfer accounts, default disbursement expense account, Mode of Payment per channel, GENERAL project, donation VAT treatment (Out of scope / Exempt — see 7.11).
- **Membership Settings**: tiers table (tier, monthly amount, Item, Subscription Plan, colour), membership income account, Sales Taxes and Charges Template (optional), dunning retry days (default 3 and 7), honorary threshold (lifetime giving), honorary policy (7.5.5).
- **Moyasar Settings** (as v1): mode (Test only), publishable key, secret key (Password), webhook secret (Password). site_config fallback.

### 5.3 Chart of accounts (created by setup, under the default company)

| Account | Type | Used by |
|---|---|---|
| Restricted Donations Income | Income | Donations to Restricted projects |
| Unrestricted Donations Income | Income | Donations to GENERAL |
| Membership Income | Income | Membership Sales Invoices (project GENERAL) |
| Fund Transfers In / Fund Transfers Out | Income (contra) | Fund Allocation (D4) |
| Project Program Expenses | Expense | Disbursements (default; per request overridable) |
| Moyasar Clearing | Bank | Mode of Payment "Moyasar Online" |
| Online Store Clearing, mada POS Clearing | Bank | Their Modes of Payment |
| Main Bank Account | Bank | Bank transfers, disbursements |

Gateway settlement from clearing accounts to the bank, and gateway fees, are recorded manually by the Accountant in v2 (out of scope to automate).

### 5.4 Fixtures shipped in the app

Custom Field, Property Setter, Role, Custom DocPerm, Workflow, Workflow State, Workflow Action Master, Mode of Payment, Customer Group "Donors", Item Group "Memberships", Print Format (donation receipt, gift card, annual statement, membership invoice in Arabic), Number Card, Dashboard Chart, Workspace, Notification (where native Notification is enough). Accounts, Items, Subscription Plans and the GENERAL project are company-specific, so they are created by an idempotent `after_install` / `after_migrate` setup, not by fixtures.

---

## 6. Accounting design

### 6.1 Postings

| Event | Document | Debit | Credit | Project on both lines |
|---|---|---|---|---|
| Donation submitted | Journal Entry | Mode of Payment account (clearing or bank) | Restricted or Unrestricted Donations Income | Donation project |
| Donation cancelled (refund / reversal) | Journal Entry cancelled (native reversal of GL) | | | |
| Membership invoice | Sales Invoice (native, from Subscription) | Debtors (party = donor) | Membership Income (+ VAT if configured) | GENERAL |
| Membership charge succeeded | Payment Entry (native) | Moyasar Clearing | Debtors | GENERAL |
| Disbursement paid | Journal Entry | Expense account | Bank | Request project |
| Fund allocation approved | Journal Entry | Fund Transfers Out | Fund Transfers In | Out: GENERAL · In: target project |

### 6.2 Balances (D2)

```
balance(P) = Σ (credit − debit)  over GL Entry
             where project = P and is_cancelled = 0
             and account.root_type in (Income, Expense)
committed(P) = Σ amount of Disbursement Requests of P in state "Approved" (approved, not yet paid)
available(P) = balance(P) − committed(P)
progress(P)  = (donations income of P) ÷ target_amount
```

One function, `ataa_hub.accounting.get_project_balance(project)`, is used by the controllers, the API, the portal, the event screen, Number Cards (type "Custom") and the reports.

### 6.3 Restricted-fund rules

- A disbursement from a project can never exceed `available(P)`. Checked on **submit for review, accountant approval, executive approval and payment**, with the project row locked (`SELECT … FOR UPDATE`) so two approvals cannot spend the same riyal.
- Donations to GENERAL are unrestricted. They reach a restricted project only through an approved **Fund Allocation**, which cannot exceed `available(GENERAL)`.
- Reports always show restricted and unrestricted balances in separate columns.

---

## 7. Features and user journeys

### 7.1 Public donation page `/donate` (Moyasar, as v1 + ERPNext)

1. Donor sees public projects: image, title, progress bar (from GL), impact label.
2. Picks a project, a ready amount or a custom amount, optional name / mobile / email, optional **gift** (7.6).
3. Server creates a **Draft Donation** (`payment_status = Awaiting Payment`) and returns its id.
4. Moyasar form shows with the **publishable key only**, amount in halalas, donation id in `metadata`.
5. Moyasar redirects to `/donate/callback?id=<payment_id>`; also sends a **webhook**.
6. Both paths call one function that fetches the payment **with the secret key** and checks status `paid`, amount and donation id. Nothing from the browser is trusted.
7. On success: idempotency_key `moyasar:<payment_id>` is set, the Donation is **submitted** (GL posted), the donor is matched or created (Customer by mobile), and the thank-you page shows the receipt number and a link to the verification page.
8. Callback and webhook racing each other submit the Donation once (row lock + unique idempotency key).

### 7.2 Online stores and partners (API)

As v1, contract in [API.md](API.md). `create_donation` now **creates and submits** a Donation (GL posted in the same request). New optional `gift` and `event_code`. Responses include `impact_units`. Channel and Mode of Payment come from the API Client, never from the request body.

### 7.3 POS terminals and Event mode (example: Clock Tower Booth – برج الساعة)

- The Accountant creates **Fundraising Event** `CLOCKTOWER-2026`: location, dates, target, projects, terminals T01-CLOCKTOWER and T02-CLOCKTOWER (each tied to a POS API Client).
- Terminals send `create_donation` with `pos` fields and `event_code`. The API rejects:
  - `EVENT_NOT_ACTIVE` (403) if the event is not Active or `paid_at` is outside its window.
  - `TERMINAL_NOT_IN_EVENT` (403) if the (API client, terminal_id) pair is not listed on the event.
  - `PROJECT_NOT_ALLOWED` (403) if the project is not one of the event's projects.
- **Live screen** `/event/<event_code>` for a large display at the booth: total vs target (progress bar), live feed of latest donations (amount + project, **no donor names**), totals per project, per terminal, last hour.
- Updates arrive through `frappe.publish_realtime` on Donation submit, no page refresh. The page is public, so the M0 spike verifies that guest sockets receive events on the chosen version; if they don't, the page falls back to polling a cached endpoint every 10 s.
- Report **Event Performance**: per hour, per terminal, per card scheme.

### 7.4 Bank transfer (manual)

Accountant creates a Donation (channel Bank Transfer, Mode of Payment Bank Transfer) with the proof attached, keeps it Draft until the money appears on the statement, then **submits** it (GL posted). Proof is mandatory to submit.

### 7.5 Memberships

#### 7.5.1 Tiers
Bronze 50, Silver 100, Gold 250, Platinum 500 SAR / month (amounts in Membership Settings). Each paid tier = one Item (group "Memberships") + one monthly Subscription Plan. **Honorary** is not purchasable (7.5.5).

#### 7.5.2 Sign-up
1. Donor picks a tier on `/membership` (logged in or with email + mobile).
2. Server creates/matches the Customer, then a Draft "sign-up intent" is held in the session; the Moyasar form charges the first month with **save card** enabled.
3. Server verifies the payment with the secret key and reads the returned **token**, checks its status with `GET /v1/tokens/:id` (must be `active`), stores it in **Donor Payment Method**.
4. Server creates the **Subscription** (party = Customer, plan = tier, monthly, invoice generated at the beginning of the period, submit invoice on), generates the first **Sales Invoice** through the native Subscription process, and records a **Payment Entry** against it for the verified first payment.
5. Customer `membership_tier = tier`, `membership_status = Active`, `member_since = today`, Contact and portal User created (login by email link).

#### 7.5.3 Monthly charging (daily scheduler job)
1. ERPNext Subscription generates the monthly Sales Invoice (native scheduler).
2. Our daily job selects submitted, unpaid Sales Invoices with `is_membership = 1` and `due_date ≤ today` that have no Processing/Succeeded attempt and whose next retry date has arrived.
3. For each: create a **Membership Charge Attempt** in status Processing **and commit** before calling Moyasar (crash-safe), then `POST /v1/payments` with `source: {type: "token", token}`, amount, and `metadata: {invoice, attempt}`.
4. Verify the result **by fetching the payment** with the secret key. On `paid`: create and submit the Payment Entry, mark the attempt Succeeded, send an Arabic receipt email.
5. On failure: attempt Failed, `next_retry_on` = +3 days (attempt 2), then +7 days (attempt 3); Customer `membership_status = Payment Pending`; donor notified each time with a link to update the card.
6. After the 3rd failure: `membership_status = Suspended`, Subscription left unpaid (native status), Accountant notified.
7. An attempt left in Processing (timeout, crash) is **never re-charged blindly**: the reconciliation job resolves it from Moyasar first, otherwise it becomes Needs Review for the Accountant.

#### 7.5.4 Self-service (portal, whitelisted methods)
- `change_tier`: switches the Subscription plan from the next billing period.
- `update_card`: new Moyasar save-card flow (1 SAR verification handled by Moyasar), new token becomes default, old token deleted at Moyasar (`DELETE /v1/tokens/:id`) and marked Deleted. If the membership is Payment Pending, the open invoice is retried immediately.
- `cancel_membership`: sets the Subscription to cancel at period end; status shows Cancelled after the period ends.

#### 7.5.5 Honorary members
- Monthly job: Customers whose `lifetime_giving` ≥ threshold become Honorary (`honorary_since = today`). The Executive Director can also grant it manually (button on Customer, ED role only).
- Policy for a donor who already pays a tier (configurable in Membership Settings, default **"keep paid membership, show Honorary badge"**; alternative "cancel paid membership at period end"). To be confirmed with the association (Open question Q3).

### 7.6 Gift donations
- Any donation (page or API) can be a gift: recipient name, mobile, email, occasion, message.
- On submit: an Arabic **gift card** (Print Format + public page `/gift/<gift_token>`, unguessable token) is emailed to the recipient if an email is given. The donor gets the shareable link for WhatsApp/SMS (sending SMS/WhatsApp is out of scope).
- The gift page shows the occasion, message, project and impact, never the amount unless the donor opts in (`show_amount_on_gift`).

### 7.7 Donor portal (Website User, own data only)

| Page | Content |
|---|---|
| `/my-giving` | **Membership card first** (7.7.1), then impact per project, then recent donations |
| `/my-giving/donations` | Full history, filters by date / project / channel |
| `/my-giving/receipts` | PDF receipts (Arabic Print Format) |
| `/my-giving/gifts` | Gifts sent, with their links |
| `/my-giving/statement` | Annual giving statement PDF (choose year) |

#### 7.7.1 Membership card (read live, nothing duplicated)
| Element | Source |
|---|---|
| Tier name + visual (Bronze / Silver / Gold / Platinum / Honorary) | Customer.membership_tier |
| Status: Active / Payment Pending / Suspended / Cancelled | Customer.membership_status |
| Member since | Customer.member_since |
| Last successful charge (date, amount) | Latest submitted Payment Entry against a membership Sales Invoice of the donor |
| Next charge date | Subscription current period (`current_invoice_end` + 1 day / next invoice due date) |
| Card on file: brand •••• last4, expiry | Default active Donor Payment Method |
| Actions | Change tier · Update card · Cancel membership |

Honorary: shows "عضو شرفي منذ <date>" and **no billing fields**.

Portal security: permission query conditions restrict Donation, Sales Invoice, Payment Entry and Donor Payment Method to the Customer(s) linked to the logged-in user's Contact.

### 7.8 Disbursement workflow (as v1, now posting to the GL)

```
Draft ──(Project Manager: Submit for Review)──▶ Pending Accountant Review
Pending Accountant Review ──(Accountant: Approve)──▶ Pending Executive Approval
Pending Accountant Review ──(Accountant: Return)──▶ Draft
Pending Executive Approval ──(Executive Director: Approve)──▶ Approved   [docstatus 1]
Pending Executive Approval ──(Executive Director: Reject, reason required)──▶ Rejected
Approved ──(Accountant: Mark Paid)──▶ Paid   → Journal Entry Dr expense / Cr bank, project = request project
```

- Balance check (6.3) at every forward step, including Mark Paid.
- Cancelling the Journal Entry (hook on Journal Entry `on_cancel`) moves the request back to **Approved** and clears `journal_entry`, so it can be paid again correctly.
- Every transition tracked; next person notified in-app.

### 7.9 Fund Allocation workflow

`Draft ──(Accountant or Project Manager: Request)──▶ Pending Executive Approval ──(Executive Director: Approve)──▶ Approved` (JE posted, D4) or `──(Reject, reason)──▶ Rejected`. Amount ≤ `available(GENERAL)` at request and approval. Cancelling reverses the JE.

### 7.10 Impact units

- Project: `impact_unit_label`, `impact_units_per_sar`.
- Donation stores `impact_units = amount × rate` **at submit** (later rate changes don't rewrite history).
- Portal shows the donor's impact per project; **Impact Report** shows units per project per period.

### 7.11 Receipts and ZATCA e-invoicing

- **Membership Sales Invoices** are tax documents: reported as **simplified (B2C) e-invoices** to the **ZATCA sandbox** through the ZATCA app (D5). Our app supplies the company/branch tax data, the tax template from Membership Settings, and an Arabic invoice Print Format with the ZATCA QR.
- **Donations are not tax invoices**: they get an Arabic **donation receipt** Print Format with a QR code to `/verify/<receipt_token>`, a public page confirming receipt number, date, amount and project (no donor data).
- **VAT treatment is configuration, not code**: memberships use whatever Sales Taxes and Charges Template is set (none, 0 %, exempt or 15 %); donations have a setting Out of scope / Exempt printed on the receipt. If a tax advisor decides donations are taxable, they would need to become Sales Invoices: recorded as Open question Q1, not built.

---

## 8. Roles and permissions

| Data | Executive Director | Project Manager | Accountant | API Client | Donor (portal) | System Manager |
|---|---|---|---|---|---|---|
| Project | Read | Create / write **own** | Read | Public ones via API | Public ones on pages | All |
| Donation | Read | Read (own projects) | Read, create Bank Transfer, submit, cancel | Create via API only | **Own** only | All |
| Customer (donor) | Read | Read | Read / write | — | Own profile | All |
| Disbursement Request | Read, approve / reject | Create / submit for review (own projects) | Review, return, mark paid | — | — | All |
| Fund Allocation | Approve / reject | Request | Request, read | — | — | All |
| Subscription, Sales Invoice, Payment Entry (membership) | Read | — | Read / write (native Accounts roles) | — | **Own** only | All |
| Donor Payment Method | — | — | Read (masked) | — | **Own** (masked), via portal actions | All |
| Membership Charge Attempt | Read | — | Read / resolve Needs Review | — | — | All |
| Fundraising Event | Read | Read | Create / write | Validated through API | Live screen (public) | All |
| API Clients, Settings (Ataa, Membership, Moyasar) | Read API Clients | — | — | — | — | **Only role that edits settings and generates keys** |
| Honorary grant | Grant / revoke | — | — | — | — | All |

The Accountant role is our `Donations Accountant` combined with ERPNext's native `Accounts User`. Row rule: Project Manager sees only projects where they are the project user/manager, and their donations and requests (permission query conditions + `has_permission`).

> Note: the change request text was cut off in section 7 ("System Manager for settings (Moyasar, …"). The table assumes System Manager owns all settings DocTypes and API key generation. Confirm or correct (Q6).

---

## 9. Developer checklist (visible in code)

### 9.1 `hooks.py` → `doc_events`
| DocType | Event | Action |
|---|---|---|
| Donation | `on_submit` | Post JE, freeze impact units, recompute donor `lifetime_giving`, `publish_realtime` (event screen, dashboards), send receipt / gift card |
| Donation | `on_cancel` | Cancel JE, recompute lifetime giving, publish realtime |
| Payment Entry | `on_submit` / `on_cancel` | If against a membership invoice: update `membership_status`, last charge; reverse on cancel |
| Subscription | `on_update` | Sync `membership_tier`, `membership_status`, `membership_subscription` on Customer |
| Journal Entry | `validate` | If it hits a donation/membership/disbursement account, `project` is mandatory on that line (D1) |
| Journal Entry | `on_cancel` | If created by a Disbursement Request → back to Approved; by a Fund Allocation → cancel it |
| Sales Invoice | `validate` | Membership invoices: set `is_membership`, project GENERAL, tax template from settings |

### 9.2 `scheduler_events`
| Frequency | Job |
|---|---|
| Daily | Charge due membership invoices |
| Daily | Dunning retries (same job, filtered by `next_retry_on`) |
| Daily | Reconcile Moyasar payments vs Donations, Payment Entries and Processing attempts |
| Monthly | Evaluate Honorary memberships |
| Monthly | Email impact summary to active members |

### 9.3 Whitelisted methods
- External API: `ataa_hub.api.v1.list_projects`, `create_donation`, `get_donation`.
- Portal: `ataa_hub.portal.membership.change_tier`, `update_card`, `cancel_membership`, `start_signup`.
- Payments: `ataa_hub.payments.moyasar_callback` (page), `moyasar_webhook`.
- Public pages data: `ataa_hub.public.event_feed` (cached), gift and verify pages (token lookup).

### 9.4 Controllers
- **Donation**: project accepts donations, amount > 0 (2 decimals), POS fields, idempotency, bank-transfer proof, GL posting, cancel reason, impact.
- **Disbursement Request / Fund Allocation**: balance checks at every transition with row lock, JE creation, rejection reason.
- **Donor Payment Method**: token never exposed (Password field, never serialized), masked title, delete at Moyasar on removal.

---

## 10. Dashboards and reports

### Workspaces
- **Executive Director**: donations this month, active members and MRR, approvals waiting, restricted vs unrestricted balance, monthly trend, donations by channel, events.
- **Project Manager**: own projects (GL balance, available, progress, impact), latest donations, own requests.
- **Accountant**: bank transfers to verify, requests to review/pay, failed and Needs Review charge attempts, latest API donations, reconciliation status.

### Script Reports
| Report | Content |
|---|---|
| Donations by Project and Channel | Date filter, Excel export |
| Monthly Project Statement | Per project: restricted / unrestricted, income, transfers, expenses, balance (replaces the monthly Excel) |
| Moyasar Reconciliation | Moyasar paid payments vs Donations and membership Payment Entries; flags missing / amount / status mismatches |
| Membership Report | Active per tier, MRR, new, payment pending, suspended, cancelled, churn |
| Impact Report | Units per project per period |
| Event Performance | Per hour, terminal, card scheme |

Native reports used in the demo: **General Ledger** and **Profit and Loss** filtered by project.

---

## 11. Non-functional requirements

| Area | Requirement |
|---|---|
| Security | Secret keys and tokens only in Password fields / site_config; never in a browser, API response, log or repo. Payment results always re-fetched server-side. Webhook secret checked with constant-time compare. Public pages use unguessable tokens and never show donor identity |
| Idempotency | Unique `idempotency_key` on Donation (DB constraint). Charge attempts committed before calling Moyasar. Callback + webhook processed once |
| Integrity | All money in the GL; balances computed, not stored. Paid donations never deleted, only cancelled with a reason. Submitted documents immutable |
| Audit | Track Changes on all new DocTypes; `raw_payload` kept for API donations; workflow history |
| Performance | API donation recorded (including JE) < 1 s locally; event screen update < 2 s |
| Language | Arabic RTL UI and print formats; English code and technical docs |
| Privacy | Fake data only in repo and demo; event screen and gift/verify pages show no donor personal data |
| Testability | Moyasar and ZATCA calls behind small adapters so tests inject responses; no network in unit tests |
| Compatibility | Single ERPNext major version decided in M0 (D6); no core modifications |

## 12. Out of scope (v2)

Live payments or live ZATCA; real POS hardware (Postman simulates terminals); automatic gateway settlement and fee entries; SMS / WhatsApp sending; automatic refunds through Moyasar (cancellation is recorded in ERPNext, refund done in the Moyasar dashboard); mobile app; multi-currency; standard (B2B) ZATCA invoices.

## 13. Acceptance criteria

**Accounting**
- [ ] Every submitted Donation has exactly one submitted JE with the project on both lines; cancelling the Donation cancels the JE.
- [ ] Project balance on dashboard, API, portal and event screen equals General Ledger filtered by that project.
- [ ] Restricted disbursement above available balance is blocked at submit, approval and payment.
- [ ] Unrestricted money reaches a restricted project only through an approved Fund Allocation.

**API (v1 rules kept)**
- [ ] Same request twice → one Donation, second returns 200 `duplicate: true`; same reference with another amount → 409.
- [ ] Wrong key 401, inactive client 403, unknown project 404, inactive project 403.
- [ ] `event_code` outside the window → 403 `EVENT_NOT_ACTIVE`; unknown terminal → 403 `TERMINAL_NOT_IN_EVENT`.

**Payments and memberships**
- [ ] Changing the amount in the browser doesn't change what is recorded.
- [ ] Closing the browser after paying still records the donation (webhook).
- [ ] Sign-up stores an active token, creates Subscription + first invoice + Payment Entry.
- [ ] Daily job charges a due invoice and creates the Payment Entry; a failure schedules retries at +3 and +7 days and suspends after the third.
- [ ] A Processing attempt is never charged twice.
- [ ] Membership card values match the Subscription, latest Payment Entry and Donor Payment Method.

**Portal, events, receipts**
- [ ] A donor sees only their own donations, invoices and cards.
- [ ] Event screen updates without refresh when a terminal donation is submitted.
- [ ] Receipt QR opens a verification page with the correct number, date, amount and project.
- [ ] Membership invoices are accepted by the ZATCA sandbox.

**Governance**
- [ ] Project Manager cannot see other managers' projects or approve anything.
- [ ] Every workflow transition is recorded with user and time.

## 14. Demo script (7 minutes)

1. **Problem** in one sentence: monthly Excel files, no balances, WhatsApp approvals.
2. **Donation page**: test card → Donation submitted → open the **Journal Entry** and the **General Ledger** filtered by project.
3. **Postman as a store**: create → 201; retry → 200 duplicate; GL unchanged.
4. **Clock Tower booth**: open `/event/CLOCKTOWER-2026` on a second screen; send POS donations from Postman; feed updates live.
5. **Membership**: sign up as Gold → portal card; run the daily job with a due invoice → Payment Entry appears; simulate a failure → Payment Pending and retry date.
6. **Restricted funds**: PM requests more than the balance → blocked; Fund Allocation from GENERAL → ED approves → request goes through → paid → JE.
7. **Compliance**: membership invoice with ZATCA QR; donation receipt QR → verification page.
8. **API docs** at `/api-docs`.

## 15. Open questions and risks

| # | Item | Default until answered |
|---|---|---|
| Q1 | VAT treatment of donations and memberships (tax advisor) | Donations: Out of scope; memberships: template configurable, demo uses 15 % |
| Q2 | ZATCA app: `ksa_compliance` vs `zatca_erpgulf`, on v15 or v16 | Decided in M0 spike |
| Q3 | Honorary donor who already pays a tier | Keep paid membership + Honorary badge |
| Q4 | Does `lifetime_giving` include membership payments? | Yes, donations + paid membership invoices |
| Q5 | Moyasar test-mode behaviour for token charges (3DS, `cvc` requirements of test cards) | Verified in M0 with test cards; `3ds: false` for merchant-initiated charges |
| Q6 | Section 7 of the change request was truncated | System Manager owns all settings |
| R1 | Scope is large for one release | Build Plan orders work so each milestone is demoable |
| R2 | Guest realtime on public pages | Polling fallback |
| R3 | Native Subscription invoice generation timing differs between versions | Verified in M0; our job reads invoices, it doesn't create them |
