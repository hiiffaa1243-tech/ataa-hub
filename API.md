# Ataa Hub — Donations Integration API
**Version:** v2 · **Status:** Draft for approval · **Audience:** developers of online stores, POS systems and partner platforms

Supersedes v1 ([archive](docs/archive/v1/API-v1.md)). The URL path stays `ataa_hub.api.v1.*`: v2 only **adds** optional fields and two error codes, so existing v1 integrations keep working unchanged (see §11).

Ataa Hub runs on **ERPNext**. Every donation you send is booked to the association's **General Ledger** in the same request, against the project you name. Balances you read back are computed from the ledger.

---

## 1. Quick start

1. Ask the association's administrator to create an **API Client** for you. You receive an `api_key` and an `api_secret`.
2. Call `list_projects` to get the active projects and their `project_code`.
3. After every **successful** payment on your side, call `create_donation` once.
4. If the request times out, **retry with the same `external_reference`**. It is safe: the platform never records the same donation twice.

```bash
curl -X POST "https://{your-ataa-site}/api/method/ataa_hub.api.v1.create_donation" \
  -H "Authorization: token {api_key}:{api_secret}" \
  -H "Content-Type: application/json" \
  -d '{
    "external_reference": "ORDER-100245",
    "project_code": "SUQYA-01",
    "amount": 250.00,
    "paid_at": "2026-11-17T15:42:10+03:00",
    "payment_reference": "pay_8f2c1a9b"
  }'
```

---

## 2. Environments

| Environment | Base URL | Purpose |
|---|---|---|
| Local / Sandbox | `http://localhost:8000` | Development and testing with fake data |
| Production | `https://{association-site}` | Provided by the association after testing |

All endpoints are under `{base_url}/api/method/ataa_hub.api.v1.{method}`. Production traffic **must** use HTTPS.

---

## 3. Authentication

```
Authorization: token {api_key}:{api_secret}
```

- Each API Client has its own key pair and one channel: `Online Store`, `POS` or `Partner`.
- Channel and accounting (Mode of Payment) come from your API Client, **never** from the request body.
- A client can be limited to a list of projects.
- The association can **deactivate** a client at any time → `403 CLIENT_INACTIVE`.
- Never expose `api_secret` in a browser, mobile app or public repository.

---

## 4. Response format

Frappe wraps every response in `message`:

```json
{ "message": { "ok": true, "data": { } } }
```

Errors use an HTTP status code and:

```json
{
  "message": {
    "ok": false,
    "error": { "code": "PROJECT_NOT_FOUND", "message": "No project with code 'SUQYA-99'.", "details": { } }
  }
}
```

> A **wrong** key is rejected by the framework before reaching the API, so that `401` body follows Frappe's default format. Rely on the **status code**. A **missing** key returns `401 AUTH_REQUIRED` in the format above.

Amounts are numbers in SAR with up to 2 decimals. Datetimes are ISO 8601 with timezone (`+03:00`).

---

## 5. Endpoints

### 5.1 List active projects
`GET /api/method/ataa_hub.api.v1.list_projects`

Returns projects that can currently receive donations (ERPNext Project with `status = Open`, active and public), limited to your client's allowed projects. If you pass `event_code`, only that event's projects are returned.

| Query param | Required | Notes |
|---|---|---|
| `event_code` | No | e.g. `CLOCKTOWER-2026`. Unknown or inactive event → `403 EVENT_NOT_ACTIVE` |

**Response `200`**
```json
{
  "message": {
    "ok": true,
    "data": [
      {
        "project_code": "SUQYA-01",
        "title": "سقيا ضيوف الرحمن",
        "fund_type": "Restricted",
        "target_amount": 500000.00,
        "collected_amount": 312450.00,
        "progress_percent": 62.49,
        "impact_unit_label": "معتمر سُقي",
        "impact_units_per_sar": 1.0,
        "allow_custom_amount": true,
        "donation_options": [
          { "label": "سقيا 100 معتمر", "amount": 100.00 },
          { "label": "سقيا 250 معتمر", "amount": 250.00 }
        ]
      }
    ]
  }
}
```

| Field | Meaning |
|---|---|
| `fund_type` **(new)** | `Restricted` (money can only be spent on this project) or `Unrestricted` (the general fund `GENERAL`) |
| `collected_amount` | Donation income booked in the General Ledger for this project (cancelled entries excluded) |
| `impact_unit_label` **(new)** | What one unit of impact means, in Arabic |
| `impact_units_per_sar` **(new)** | Units per 1 SAR. `impact_units = amount × impact_units_per_sar` |

---

### 5.2 Create a donation
`POST /api/method/ataa_hub.api.v1.create_donation`

Call **once per successful payment**. In one database transaction the platform:

1. validates the request,
2. creates a **Donation** and **submits** it,
3. posts a **Journal Entry** (debit the channel's clearing account, credit Restricted/Unrestricted Donations Income, both lines tagged with the project),
4. links or creates the donor (ERPNext Customer, matched by mobile),
5. if `gift` is present, emails the gift card; if `event_code` is present, updates the event live screen.

If any step fails, nothing is saved and you can retry safely.

**Request body**

| Field | Type | Required | Rules |
|---|---|---|---|
| `external_reference` | string | Yes | Your unique ID for this payment. Max 140 characters. Used to prevent duplicates. |
| `project_code` | string | Yes | From `list_projects`. |
| `amount` | number | Yes | SAR, > 0, max 2 decimals. |
| `currency` | string | No | Only `SAR`. Default `SAR`. |
| `paid_at` | string | Yes | ISO 8601 with timezone. Not in the future. |
| `payment_reference` | string | Yes | Payment ID from your gateway or terminal authorization code. |
| `donor` | object | No | Omit for anonymous donations. |
| `donor.name` | string | No | |
| `donor.mobile` | string | No | `+9665XXXXXXXX`. Matches returning donors. |
| `donor.email` | string | No | Valid email. |
| `pos` | object | **POS clients** | Required when your channel is `POS`. |
| `pos.terminal_id` | string | Yes (POS) | e.g. `T01-CLOCKTOWER`. |
| `pos.card_scheme` | string | Yes (POS) | `mada`, `visa`, `mastercard`, `amex`. |
| `pos.rrn` | string | Yes (POS) | Retrieval Reference Number, 12 digits. |
| `event_code` **(new)** | string | No | Fundraising event code, e.g. `CLOCKTOWER-2026`. See §5.2.2. |
| `gift` **(new)** | object | No | Makes this donation a gift. See §5.2.1. |
| `metadata` | object | No | Extra key/value data, stored for audit, max 4 KB. |

#### 5.2.1 `gift` object (new)

| Field | Type | Required | Rules |
|---|---|---|---|
| `gift.recipient_name` | string | Yes | Max 140. |
| `gift.recipient_mobile` | string | No* | `+9665XXXXXXXX`. |
| `gift.recipient_email` | string | No* | Valid email. The gift card is emailed here. |
| `gift.occasion` | string | No | `Eid`, `Ramadan`, `Wedding`, `Newborn`, `Graduation`, `In Memory`, `Other`. Default `Other`. |
| `gift.message` | string | No | Max 500 characters. |
| `gift.show_amount` | boolean | No | Show the amount on the gift card. Default `false`. |

\* At least one of `recipient_mobile` or `recipient_email` is required. The platform sends email only; for mobile-only gifts, share the returned `gift.url` yourself.

#### 5.2.2 `event_code` rules (new)

When `event_code` is sent, the platform checks, in this order:

| Check | Error |
|---|---|
| Event exists, status `Active`, and `paid_at` within its start/end time | `403 EVENT_NOT_ACTIVE` |
| POS clients: the pair (your API Client, `pos.terminal_id`) is registered on the event | `403 TERMINAL_NOT_IN_EVENT` |
| `project_code` is one of the event's projects | `403 PROJECT_NOT_ALLOWED` |

Unknown `event_code` also returns `403 EVENT_NOT_ACTIVE` (the API does not reveal which events exist).

**Example — online store**
```json
{
  "external_reference": "ORDER-100245",
  "project_code": "SUQYA-01",
  "amount": 250.00,
  "paid_at": "2026-11-17T15:42:10+03:00",
  "payment_reference": "pay_8f2c1a9b",
  "donor": { "name": "Test Donor", "mobile": "+966500000001" }
}
```

**Example — POS terminal at the Clock Tower booth**
```json
{
  "external_reference": "TXN-T01-000731",
  "project_code": "WAFADA-02",
  "amount": 150.00,
  "paid_at": "2026-11-17T16:05:44+03:00",
  "payment_reference": "AUTH-559201",
  "event_code": "CLOCKTOWER-2026",
  "pos": { "terminal_id": "T01-CLOCKTOWER", "card_scheme": "mada", "rrn": "432118005731" }
}
```

**Example — gift from an online store**
```json
{
  "external_reference": "ORDER-100311",
  "project_code": "SUQYA-01",
  "amount": 100.00,
  "paid_at": "2026-11-17T18:20:00+03:00",
  "payment_reference": "pay_77aa01",
  "donor": { "name": "Test Donor", "mobile": "+966500000001" },
  "gift": {
    "recipient_name": "Test Recipient",
    "recipient_email": "recipient@example.test",
    "occasion": "Eid",
    "message": "عيدكم مبارك"
  }
}
```

**Response `201` — donation created and posted**
```json
{
  "message": {
    "ok": true,
    "data": {
      "donation_id": "DON-2026-00412",
      "status": "Paid",
      "project_code": "SUQYA-01",
      "amount": 250.00,
      "external_reference": "ORDER-100245",
      "duplicate": false,
      "received_at": "2026-11-17T15:42:11+03:00",
      "impact_units": 250.0,
      "impact_unit_label": "معتمر سُقي",
      "event_code": null,
      "gift": null,
      "receipt_verification_url": "https://{site}/verify/9b1f…"
    }
  }
}
```

With a gift, `gift` is:
```json
{ "url": "https://{site}/gift/3c7e…", "email_sent": true }
```

| Field | Meaning |
|---|---|
| `status` | `Paid` (submitted, posted to the ledger) or `Refunded` (cancelled later by the association) |
| `impact_units` **(new)** | `amount × impact_units_per_sar` frozen when the donation was recorded |
| `receipt_verification_url` **(new)** | Public page that confirms the receipt (no donor data). Same link as the receipt QR code |
| `gift.url` **(new)** | Unguessable link to the gift card. Treat as private: share only with the recipient |

**Response `200` — same donation sent again**: same body with `"duplicate": true`. Nothing new is recorded or posted.

---

### 5.3 Get a donation
`GET /api/method/ataa_hub.api.v1.get_donation?external_reference={value}`

Returns a donation sent by **your own** client.

**Response `200`**
```json
{
  "message": {
    "ok": true,
    "data": {
      "donation_id": "DON-2026-00412",
      "status": "Paid",
      "project_code": "SUQYA-01",
      "amount": 250.00,
      "external_reference": "ORDER-100245",
      "received_at": "2026-11-17T15:42:11+03:00",
      "impact_units": 250.0,
      "impact_unit_label": "معتمر سُقي",
      "event_code": "CLOCKTOWER-2026",
      "gift": { "url": "https://{site}/gift/3c7e…", "email_sent": true },
      "receipt_verification_url": "https://{site}/verify/9b1f…"
    }
  }
}
```

`event_code` and `gift` are `null` when not used.

---

## 6. Errors

| HTTP | Code | When | What to do |
|---|---|---|---|
| 400 | `VALIDATION_ERROR` | A field is missing or invalid. `details` lists every field and reason. | Fix the request. Don't retry unchanged. |
| 401 | `AUTH_REQUIRED` | `Authorization` header missing. | Send `token {api_key}:{api_secret}`. |
| 401 | — | Wrong key/secret (framework). | Check credentials. |
| 403 | `NOT_AN_API_CLIENT` | Valid credentials of a staff user, not an API Client. | Use your API Client's key pair. |
| 403 | `CLIENT_INACTIVE` | Client deactivated. | Contact the association. |
| 403 | `PROJECT_INACTIVE` | Project exists but doesn't accept donations (not Open, not active, or not public). | Refresh your project list. |
| 403 | `PROJECT_NOT_ALLOWED` | Project not in your client's list, or not in the event's projects. | Contact the association. |
| 403 | `EVENT_NOT_ACTIVE` **(new)** | `event_code` unknown, event not Active, or `paid_at` outside its time window. | Check the event code and terminal clock. Don't retry unchanged. |
| 403 | `TERMINAL_NOT_IN_EVENT` **(new)** | `pos.terminal_id` is not registered on the event for your client. | Ask the association to add the terminal. |
| 404 | `PROJECT_NOT_FOUND` | Unknown `project_code`. | Refresh your project list. |
| 404 | `DONATION_NOT_FOUND` | No donation with this reference for your client. | Not recorded: send it with `create_donation`. |
| 409 | `DUPLICATE_CONFLICT` | Reference already used with a **different** project, amount, event or gift recipient. | Investigate. Never reuse a reference. |
| 500 | `INTERNAL_ERROR` | Unexpected error (nothing was saved). | Retry later with the **same** reference. |

**Example `400`**
```json
{
  "message": {
    "ok": false,
    "error": {
      "code": "VALIDATION_ERROR",
      "message": "Request has 3 invalid fields.",
      "details": {
        "amount": "Must be greater than 0.",
        "pos.rrn": "Required for POS clients.",
        "gift.recipient_email": "At least one of recipient_mobile or recipient_email is required."
      }
    }
  }
}
```

**Example `403` (new)**
```json
{
  "message": {
    "ok": false,
    "error": {
      "code": "TERMINAL_NOT_IN_EVENT",
      "message": "Terminal 'T09-CLOCKTOWER' is not registered on event 'CLOCKTOWER-2026'.",
      "details": { "event_code": "CLOCKTOWER-2026", "terminal_id": "T09-CLOCKTOWER" }
    }
  }
}
```

---

## 7. Duplicate protection (idempotency)

The pair **(your API Client + `external_reference`)** is unique, enforced by a **unique database index** on the Donation, so even two identical requests arriving at the same moment produce one donation and one Journal Entry.

| You send | Platform does | Response |
|---|---|---|
| A new `external_reference` | Records and posts the donation | `201`, `duplicate: false` |
| Same reference, same project, amount, event and gift recipient | Records nothing, returns the original | `200`, `duplicate: true` |
| Same reference, any of those different | Records nothing | `409 DUPLICATE_CONFLICT`, `details.conflicting_fields` |

If the association later cancels (refunds) the donation, a retry of the same reference still returns the original with `status: "Refunded"` and does **not** create a new donation.

---

## 8. What happens in ERPNext (for reviewers)

| API action | ERPNext result |
|---|---|
| `create_donation` | `Donation` (docstatus 1) + `Journal Entry` (docstatus 1): Dr channel clearing account / Cr Restricted or Unrestricted Donations Income, `project` set on both lines |
| Donor sent | `Customer` in group *Donors* (matched by mobile) + `Contact`; `lifetime_giving` recomputed |
| Association cancels a donation | Donation and its Journal Entry cancelled; GL reversed; `status` becomes `Refunded` |
| `collected_amount` | Sum of donation income GL entries for the project, `is_cancelled = 0` |

---

## 9. Integration checklist

- [ ] Call `create_donation` **only after** the payment succeeded on your side.
- [ ] Use a stable, unique `external_reference` per payment.
- [ ] On timeout or `500`, retry with the **same** `external_reference`.
- [ ] Refresh `list_projects` at least daily; handle `PROJECT_INACTIVE`.
- [ ] POS at events: send `event_code`, keep terminal clocks correct (`paid_at` is checked against the event window).
- [ ] Gifts: keep `gift.url` private.
- [ ] Keep `api_secret` on your server only.
- [ ] Test every error case in the Sandbox before going live.

---

## 10. Testing

- **Swagger UI** at `/api-docs`, generated from `ataa_hub/public/openapi.yaml` (OpenAPI 3.1, v2 schemas and examples).
- **Postman collection** `postman/ataa_hub_v2.postman_collection.json` + environment `postman/ataa_hub_local.postman_environment.json`, runnable with *Run collection*. Every request has tests. Folders:
  1. **Discovery**: list projects, list projects for an event.
  2. **Online store**: create, duplicate replay (200), conflict (409), get, gift donation, anonymous.
  3. **POS / Clock Tower booth**: terminal T01 and T02 donations, `TERMINAL_NOT_IN_EVENT`, `EVENT_NOT_ACTIVE` (outside window), project not in event.
  4. **Auth**: missing key (401), wrong key (401), inactive client (403), staff user (403).
  5. **Validation**: all-fields 400, POS fields, gift recipient rule, amount rules, timezone.
  6. **Project rules**: unknown (404), inactive (403), not allowed (403).
- Demo keys and the `CLOCKTOWER-2026` event are created by the demo seed (local only, fake).

---

## 11. Changelog

| Version | Date | Change |
|---|---|---|
| v1 | 2026-11 | List projects, create donation, get donation. |
| **v2** | 2026-11 | Runs on ERPNext: `create_donation` creates **and submits** a Donation that posts a Journal Entry. New optional `gift` object and `event_code`. `list_projects` adds `fund_type`, `impact_unit_label`, `impact_units_per_sar` and an `event_code` filter. Responses add `impact_units`, `impact_unit_label`, `event_code`, `gift`, `receipt_verification_url`. New errors `EVENT_NOT_ACTIVE` and `TERMINAL_NOT_IN_EVENT` (403). `status` can be `Refunded`. **Backward compatible:** no field removed or renamed, method path unchanged. |
