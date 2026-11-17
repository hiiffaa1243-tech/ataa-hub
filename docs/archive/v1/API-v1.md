# Ataa Hub — Donations Integration API
**Version:** v1 · **Status:** Draft · **Audience:** developers of online stores, POS systems and partner platforms

Ataa Hub lets any sales or payment channel report donations to a nonprofit **in real time**, instead of sending monthly spreadsheets. Each donation is linked to a project, updates the project balance instantly, and appears on the association's dashboards.

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

All endpoints are under:
```
{base_url}/api/method/ataa_hub.api.v1.{method}
```

Production traffic **must** use HTTPS.

---

## 3. Authentication

Every request must include your key pair in the `Authorization` header:

```
Authorization: token {api_key}:{api_secret}
```

- Each API Client has its own key pair and is linked to one channel: `Online Store`, `POS` or `Partner`.
- The channel is taken from your API Client, not from the request body.
- The association can **deactivate** a client at any time. All its requests then return `403 CLIENT_INACTIVE`.
- Never expose your `api_secret` in a browser, mobile app or public repository. Call the API from your server.

---

## 4. Response format

The platform runs on the Frappe framework, which wraps every successful response in a `message` object:

```json
{
  "message": {
    "ok": true,
    "data": { }
  }
}
```

Errors use an HTTP status code and this body:

```json
{
  "message": {
    "ok": false,
    "error": {
      "code": "PROJECT_NOT_FOUND",
      "message": "No project with code 'SUQYA-99'.",
      "details": { }
    }
  }
}
```

> A **wrong** key is rejected by the framework's authentication layer before your request reaches the API, so that `401` body follows the framework's default format. Rely on the **status code**. A **missing** key returns `401 AUTH_REQUIRED` in the format above.

---

## 5. Endpoints

### 5.1 List active projects
`GET /api/method/ataa_hub.api.v1.list_projects`

Returns the projects that can currently receive donations. If your client is restricted to specific projects, only those are returned.

**Response `200`**
```json
{
  "message": {
    "ok": true,
    "data": [
      {
        "project_code": "SUQYA-01",
        "title": "سقيا ضيوف الرحمن",
        "target_amount": 500000.00,
        "collected_amount": 312450.00,
        "progress_percent": 62.49,
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

---

### 5.2 Create a donation
`POST /api/method/ataa_hub.api.v1.create_donation`

Call this **once per successful payment**. The donation is recorded with status `Paid`.

**Request body**

| Field | Type | Required | Rules |
|---|---|---|---|
| `external_reference` | string | Yes | Your unique ID for this payment (order number, terminal transaction ID). Max 140 characters. Used to prevent duplicates. |
| `project_code` | string | Yes | From `list_projects`. |
| `amount` | number | Yes | In SAR, greater than 0, max 2 decimal places. |
| `currency` | string | No | Only `SAR` is accepted. Default `SAR`. |
| `paid_at` | string | Yes | ISO 8601 with timezone, e.g. `2026-11-17T15:42:10+03:00`. Cannot be in the future. |
| `payment_reference` | string | Yes | The payment ID from your payment gateway or terminal. |
| `donor` | object | No | Omit for anonymous donations. |
| `donor.name` | string | No | |
| `donor.mobile` | string | No | Saudi format `+9665XXXXXXXX`. Used to match returning donors. |
| `donor.email` | string | No | Valid email. |
| `pos` | object | **POS clients only** | Required when your client channel is `POS`. |
| `pos.terminal_id` | string | Yes (POS) | Terminal identifier. |
| `pos.card_scheme` | string | Yes (POS) | `mada`, `visa`, `mastercard` or `amex`. |
| `pos.rrn` | string | Yes (POS) | Retrieval Reference Number, 12 characters. |
| `metadata` | object | No | Any extra key/value data. Stored for audit, max 4 KB. |

**Example — online store**
```json
{
  "external_reference": "ORDER-100245",
  "project_code": "SUQYA-01",
  "amount": 250.00,
  "paid_at": "2026-11-17T15:42:10+03:00",
  "payment_reference": "pay_8f2c1a9b",
  "donor": {
    "name": "Test Donor",
    "mobile": "+966500000001"
  }
}
```

**Example — POS terminal at an event**
```json
{
  "external_reference": "TXN-T01-000731",
  "project_code": "WAFADA-02",
  "amount": 150.00,
  "paid_at": "2026-11-17T16:05:44+03:00",
  "payment_reference": "AUTH-559201",
  "pos": {
    "terminal_id": "T01-HAJJ-EXPO",
    "card_scheme": "mada",
    "rrn": "432118005731"
  }
}
```

**Response `201` — donation created**
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
      "received_at": "2026-11-17T15:42:11+03:00"
    }
  }
}
```

**Response `200` — same donation sent again**
Same body as above, with `"duplicate": true`. Nothing new is recorded.

---

### 5.3 Get a donation
`GET /api/method/ataa_hub.api.v1.get_donation?external_reference={value}`

Check whether a donation you sent was recorded. You can only read donations sent by your own client.

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
      "received_at": "2026-11-17T15:42:11+03:00"
    }
  }
}
```

---

## 6. Errors

| HTTP | Code | When it happens | What to do |
|---|---|---|---|
| 400 | `VALIDATION_ERROR` | A field is missing or invalid. `details` lists each field and the reason. | Fix the request. Do not retry unchanged. |
| 401 | `AUTH_REQUIRED` | The `Authorization` header is missing. | Send `token {api_key}:{api_secret}`. |
| 401 | — | Wrong `api_key` / `api_secret` (rejected by the framework). | Check your credentials. |
| 403 | `NOT_AN_API_CLIENT` | Valid credentials, but they belong to a staff user, not an API Client. | Use the key pair issued for your API Client. |
| 403 | `CLIENT_INACTIVE` | Your API Client was deactivated by the association. | Contact the association. |
| 403 | `PROJECT_INACTIVE` | The project exists but is not accepting donations. | Refresh your project list. |
| 403 | `PROJECT_NOT_ALLOWED` | Your client is not allowed to donate to this project. | Contact the association. |
| 404 | `PROJECT_NOT_FOUND` | Unknown `project_code`. | Refresh your project list. |
| 404 | `DONATION_NOT_FOUND` | No donation with this `external_reference` for your client. | The donation was not recorded. Send it with `create_donation`. |
| 409 | `DUPLICATE_CONFLICT` | The `external_reference` was already used **with a different amount or project**. | Investigate. Never reuse a reference for a different payment. |
| 500 | `INTERNAL_ERROR` | Unexpected server error. | Retry later with the **same** `external_reference`. |

**Example `400`**
```json
{
  "message": {
    "ok": false,
    "error": {
      "code": "VALIDATION_ERROR",
      "message": "Request has 2 invalid fields.",
      "details": {
        "amount": "Must be greater than 0.",
        "pos.rrn": "Required for POS clients."
      }
    }
  }
}
```

---

## 7. Duplicate protection (idempotency)

The pair **(your API Client + `external_reference`)** is unique.

| You send | Platform does | Response |
|---|---|---|
| A new `external_reference` | Records the donation | `201`, `duplicate: false` |
| The same `external_reference`, same project and amount | Records nothing, returns the original | `200`, `duplicate: true` |
| The same `external_reference`, different project or amount | Records nothing | `409 DUPLICATE_CONFLICT` |

This makes retries safe after timeouts or network failures.

---

## 8. Integration checklist

- [ ] Call `create_donation` **only after** the payment succeeded on your side.
- [ ] Use a stable, unique `external_reference` per payment.
- [ ] On timeout or `500`, retry with the **same** `external_reference`.
- [ ] Refresh `list_projects` at least daily, and handle `PROJECT_INACTIVE`.
- [ ] Keep `api_secret` on your server only.
- [ ] Test every error case in the Sandbox before going live.

---

## 9. Testing

Interactive documentation (Swagger UI, generated from `ataa_hub/public/openapi.yaml`) is served by the platform at `/api-docs`.

A **Postman collection** is provided in `/postman/ataa_hub_v1.postman_collection.json` with:
- An environment for `base_url`, `api_key`, `api_secret`.
- Ready requests for every endpoint.
- Error scenarios: wrong key, unknown project, duplicate, conflict, invalid POS fields.

---

## 10. Changelog

| Version | Date | Change |
|---|---|---|
| v1 (draft) | 2026-11 | First version: list projects, create donation, get donation. |
