"""Thin Moyasar client used by memberships (PRD §7.5).

Only the server talks to these endpoints, always with the *secret* key from
Moyasar Settings. Tests replace the client with a fake through `get_client()`.

Two kinds of error matter for money:
- `MoyasarError`: Moyasar answered and refused (4xx). Nothing was charged.
- `MoyasarUnavailable`: timeout / network / 5xx. The outcome is unknown, so the
  caller must NOT retry blindly; it keeps the attempt in Processing and the
  reconciliation job asks Moyasar later (by the `given_id` we chose up front).
"""

import frappe
import requests
from frappe import _

from ataa_hub.ataa_hub.doctype.moyasar_settings.moyasar_settings import get_moyasar_config

MOYASAR_API = "https://api.moyasar.com/v1"
TIMEOUT = 20


class MoyasarError(Exception):
	def __init__(self, message, status_code=None):
		super().__init__(message)
		self.status_code = status_code


class MoyasarUnavailable(Exception):
	pass


class NotFound(MoyasarError):
	pass


class MoyasarClient:
	def __init__(self, secret_key: str | None = None):
		self.secret_key = secret_key or get_moyasar_config().secret_key
		if not self.secret_key:
			frappe.throw(_("أضيفي المفتاح السري لميسّر في إعدادات ميسّر."))

	def _call(self, method, path, **kwargs):
		try:
			response = requests.request(
				method, f"{MOYASAR_API}{path}", auth=(self.secret_key, ""), timeout=TIMEOUT, **kwargs
			)
		except requests.RequestException as e:
			raise MoyasarUnavailable(str(e)) from e
		if response.status_code >= 500:
			raise MoyasarUnavailable(f"Moyasar {response.status_code}")
		if response.status_code == 404:
			raise NotFound("not found", 404)
		if response.status_code >= 400:
			try:
				message = response.json().get("message") or response.text
			except ValueError:
				message = response.text
			raise MoyasarError(message, response.status_code)
		return response.json() if response.content else {}

	# ---------------------------------------------------------------- payments
	def fetch_payment(self, payment_id: str) -> dict:
		return self._call("GET", f"/payments/{payment_id}")

	def charge_token(
		self, *, given_id: str, token: str, amount_halalas: int, description: str, metadata: dict
	) -> dict:
		"""Merchant-initiated charge of a saved card. `given_id` makes it idempotent at Moyasar."""
		return self._call(
			"POST",
			"/payments",
			json={
				"given_id": given_id,
				"amount": amount_halalas,
				"currency": "SAR",
				"description": description,
				"source": {"type": "token", "token": token, "3ds": False, "manual": False},
				"metadata": metadata,
			},
		)

	# ------------------------------------------------------------------ tokens
	def fetch_token(self, token_id: str) -> dict:
		return self._call("GET", f"/tokens/{token_id}")

	def delete_token(self, token_id: str) -> None:
		self._call("DELETE", f"/tokens/{token_id}")


def get_client():
	"""Single entry point, so tests can patch it with a fake Moyasar."""
	return MoyasarClient()
