# M0 Spike — status and findings

Goal: settle PRD decisions D5 (ZATCA app), D6 (ERPNext version), R2 (guest realtime), R3 (Subscription timing) and Q5 (Moyasar token charges) before building.

## Status

| Part | Status |
|---|---|
| Desk research on the ZATCA apps | **Done** (below) |
| Spike environment (`docker/spike/`) | Done |
| Spike run | **Done 2026-11-17** in GitHub Codespaces (4 cores / 16 GB), because the local PC has 8 GB RAM, ~9 GB free disk and a broken Virtual Machine Platform install |

## Results

| # | Check | Result |
|---|---|---|
| 0 | Python 3.14 + Node 24 | PASS |
| 1a/1b | Frappe + ERPNext **16.60.0**, site created | PASS |
| 2 | `ksa_compliance` install + migrate | PASS |
| 3 | `zatca_erpgulf` install + migrate | PASS |
| 4 | Subscription timing | PASS (after fixing the check's import path). First invoice created **and submitted on insert**, posting = due = start date; period fields then point to the next period. `process(posting_date)` exists. With `generate_new_invoices_past_due_date = 0` no new invoice while the previous is unpaid; with 1 the next invoice is created on the period start |
| 5 | Guest socket.io | **Rejected**: "Missing cookie and authorization header" → public event screen uses polling |
| 6 | Moyasar token charge | PASS. Token from test card 4111… created with status `save_only` (no 3DS); charge with `3ds: false` → `paid`, message `APPROVED`. Keys supplied as Codespaces secrets, never in the repo |

## Decisions (written into PRD v2.1)

- **D6:** ERPNext v16.
- **D5:** `ksa_compliance`; `zatca_erpgulf` fallback.
- **R2:** public `/event/<code>` polls a cached endpoint every 5 s; staff desk pages use realtime.
- **R3:** keep `generate_new_invoices_past_due_date = 0`; our daily job charges invoices that ERPNext creates.
- **Q5:** closed. Merchant-initiated token charges with `3ds: false` work in test mode.

Moyasar test keys live in Codespaces secrets `MOYASAR_PUBLISHABLE_KEY` / `MOYASAR_SECRET_KEY` (repo-scoped). After changing a secret, restart the Codespace.

## Research findings (2026-11-17)

| | `ksa_compliance` (LavaLoon) | `zatca_erpgulf` (ERPGulf) |
|---|---|---|
| Licence | AGPL-3.0 | MIT |
| Declared Frappe range (`pyproject.toml`) | `>=15.0.0,<17.0.0` → v16 allowed | `>=14.0.0,<17.0.0` → v16 allowed |
| Stated support | Frappe Cloud listing: v15 | README: v13, 14, 15 (mentions v16.54 update notice) |
| Branch | `master` | `main` |
| Simplified (B2C) invoices | Listed | Not stated in README |
| ZATCA sandbox | Listed | Not stated in README |

Reading: both apps *allow* v16 in their dependency range, but neither publicly claims v16 support. `ksa_compliance` still matches our needs best (simplified invoices + sandbox). The install test (check 2/3) decides.

ERPNext v16 requires **Python 3.14** and **Node 24** (MariaDB 11.8 recommended); the spike installs these itself inside the `frappe/bench` container.

## How to run (once Docker is installed)

```bash
cd docker/spike
docker compose up
```

First run ~20–30 min. The report is printed at the end and saved in the container:

```bash
docker compose exec frappe cat /home/frappe/spike-report.md
```

Optional check 6 (Moyasar token charge): put `MOYASAR_PUBLISHABLE_KEY=pk_test_…` and `MOYASAR_SECRET_KEY=sk_test_…` in `docker/spike/.env` (git-ignored). Test keys only.

Remove everything afterwards: `docker compose down -v`.

## Checks

| # | Check | Decides |
|---|---|---|
| 0 | Python 3.14 + Node 24 toolchain | — |
| 1a/1b | bench init `version-16` + ERPNext site | D6 |
| 2 | `ksa_compliance` installs + migrates on its own site | D5 |
| 3 | `zatca_erpgulf` installs + migrates on its own site | D5 fallback |
| 4 | Monthly Subscription: invoices after insert, after `process()` today and next month; `process()` signature; native scheduler jobs | R3, M5 design |
| 5 | Guest socket.io client receives `publish_realtime` (rooms `website`, `all`, broadcast) | R2 |
| 6 | Moyasar test token: created active without 3DS? charge with `3ds:false` paid? | Q5 |

## Decision rule

- Checks 1 + 2 pass → **v16 + ksa_compliance**.
- 2 fails, 3 passes → v16 + zatca_erpgulf, confirm simplified invoices manually.
- Both fail → rerun with `FRAPPE_BRANCH=version-15 PYTHON_VERSION=3.11 NODE_VERSION=18` → v15.
- Check 5 fails → event screen uses polling (already the planned fallback).
