# Setup and demo guide

How to run Ataa Hub, what the demo contains, and the optional Moyasar and ZATCA steps. Back to the [README](../README.md).

## Run it in the browser (no install)

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/hiiffaa1243-tech/ataa-hub)

1. Click the button (uses your own GitHub account's free Codespaces hours; pick the 4-core machine).
2. When the editor opens, run in its terminal:
   ```bash
   cd docker && docker compose up
   ```
3. After about 25 minutes the log shows `Ataa Hub is starting`. Open the **Ports** tab, then port **8000** in the browser, and sign in with an account from the table below.
4. Stop the Codespace when you are done, so it does not use your hours.

## Run it locally (Docker)

Needs [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
git clone https://github.com/hiiffaa1243-tech/ataa-hub.git
cd ataa-hub/docker
docker compose up
```

The first start takes **about 25 minutes**: it installs Python 3.14 and Node 24, builds an ERPNext v16 bench, creates the site, finishes the setup wizard headless for a fake association (**جمعية عطاء التجريبية**) and loads the demo data. `DEMO_DATA=0 docker compose up` starts an empty association instead.

| URL | What |
|---|---|
| http://localhost:8000/login | Staff sign-in; staff land on their dashboard `/desk/ataa-home` |
| http://localhost:8000/donate | Public donation page |
| http://localhost:8000/event/CLOCKTOWER-2026 | Live event screen (Clock Tower booth) |
| http://localhost:8000/membership | Membership sign-up |
| http://localhost:8000/my-giving | Donor portal |
| http://localhost:8000/api-docs | Interactive API documentation (Swagger UI) |

## Demo accounts (local only, fake people)

| Role | Email | Password | Start at |
|---|---|---|---|
| Executive Director | `ed@ataa.test` | `Ataa@Demo2026` | Dashboard: KPIs and approvals |
| Donations Accountant | `accountant@ataa.test` | `Ataa@Demo2026` | Dashboard: custody, payments, bank transfers |
| Project Manager (Suqya + Wafada) | `pm@ataa.test` | `Ataa@Demo2026` | Dashboard: own projects, requests, custody |
| Project Manager (Iftar) | `pm2@ataa.test` | `Ataa@Demo2026` | Dashboard: own projects, requests, custody |
| Donor (Aoun member) | `donor@ataa.test` | `Ataa@Demo2026` | `/my-giving` |
| System Manager | `Administrator` | `admin` | |

API keys created by the demo seed (local only): store `demo_store_key:demo_store_secret`, POS `demo_pos_key:demo_pos_secret`, deactivated partner `demo_inactive_key:demo_inactive_secret`.

## What the demo seed contains

`bench --site <site> execute ataa_hub.setup.demo.seed` (local sites only, safe to run again):

- 6 restricted projects (5 open with photos, 1 completed) + the GENERAL fund, an API client per channel, the event **CLOCKTOWER-2026** with terminals T01 and T02.
- 22 donations over three months: confirmed and waiting bank transfers, store orders, 7 POS donations at the booth in the last hours, 2 gifts.
- One disbursement request in **each** workflow state (Draft, Pending Accountant Review, Pending Executive Approval, Approved, Rejected, Paid) and a Fund Allocation waiting for the Executive Director.
- 4 custody advances: one closed with its PDF report, one open with purchases, one fully spent and waiting for the accountant to close it, one new request.
- 4 members (Aoun, Adeed, Muazir, and a Kareem member in **Payment Pending** after a declined charge).
- 3 company bank accounts with fake IBANs for the checkout's bank-transfer option.

`bench --site <site> execute ataa_hub.setup.demo.summary` prints balances, card values and the audit trail of the paid request. CI runs the seed twice on a clean site on every push.

## Staff dashboards

`/desk/ataa-home` is one desk Page with a view per role, built from whitelisted methods (`staff_dashboard.py`) and standard Frappe UI.

| Role | Sees | Can do from the page |
|---|---|---|
| Project Manager | Own projects as cards: target vs collected, available, reserved, last 30 days; own requests and custody; latest donations | Add a project, request a disbursement, request a custody, log purchases on a custody |
| Executive Director | Donations this month, restricted / general balances, members, cash with staff; everything waiting for approval; all projects | Approve or reject requests and allocations (reason required) |
| Accountant | New custody requests, open custody with progress, close requests, requests to review and to pay, bank transfers to verify | Approve & pay or reject custody, close custody and issue the report, approve / return / mark paid |

Workspaces **Ataa Executive**, **Ataa Project Manager** and **Ataa Accountant** hold the reports and lists. Each Number Card calls a whitelisted method that checks the role first.

## Reports

| Report | For | Shows |
|---|---|---|
| Donations by Project and Channel | ED, Accountant | Count, total and average per project × channel, with a chart |
| Monthly Project Statement | ED, Accountant, PM | Opening, donations, memberships, transfers, expenses, closing per project, all from the GL |
| Moyasar Reconciliation | Accountant | Every Moyasar payment against the GL: Matched, Missing in ERPNext, Missing at Moyasar, Amount Mismatch, Cancelled |
| Membership Report | ED | Per tier: active, payment pending, suspended, new, cancelled, annual revenue, churn |
| Impact Report | ED, PM | Impact units (meals, pilgrims served…) per project and month, frozen at the time of giving |
| Event Performance | ED | One event by hour, terminal or card scheme |

## Card payments (optional)

1. Create a free account at [moyasar.com](https://moyasar.com) and copy the **test** keys (`pk_test_…`, `sk_test_…`).
2. Put them in **Moyasar Settings** in the desk, or as `MOYASAR_PUBLISHABLE_KEY` / `MOYASAR_SECRET_KEY` in the environment (Codespaces secrets). Never in the repo.
3. Pay on `/donate` or `/membership` with test card `4111 1111 1111 1111`.
4. To receive webhooks locally, expose port 8000 (e.g. `cloudflared tunnel --url http://localhost:8000`) and register `https://<tunnel>/api/method/ataa_hub.payments.moyasar_webhook` with your webhook secret.

## ZATCA sandbox (optional)

```bash
bench get-app https://github.com/lavaloon-eg/ksa_compliance
bench --site <site> install-app ksa_compliance
bench --site <site> execute ataa_hub.zatca.setup_sandbox_demo
```

`setup_sandbox_demo` sets ZATCA's published sandbox VAT number on the company and a **15 % VAT included** template for membership invoices, so a 50 SAR member still pays 50 SAR. Then fill **ZATCA Business Settings** (Fatoora server *Sandbox*), set up the CLI from that screen and onboard with the sandbox OTP. In our run the sandbox returned **Accepted with warnings** for a membership invoice; the only warning (BR-KSA-08) asks for the seller's commercial registration number. The VAT treatment of a real association is a question for its tax advisor, so nothing tax-related runs on install.

## Running the tests

```bash
docker compose exec frappe bash -lc "cd ~/frappe-bench && bench --site ataa.localhost set-config allow_tests true && bench --site ataa.localhost run-tests --app ataa_hub"
```
