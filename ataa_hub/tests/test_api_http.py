"""End-to-end through Frappe's real HTTP stack: Authorization header, JSON body, status codes.

Requests run in a separate thread with their own DB connection (like a real server),
so this class commits its fixtures and deletes them afterwards.
"""

from threading import Thread

import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.test import Client

from ataa_hub.tests.factories import iso_ago, make_api_client, make_project, reference

CODE = "TSTHTTP-01"
CLIENT_NAME = "Test HTTP Store"
KEY, SECRET = "test_http_key_ataa", "test_http_secret_ataa"


def http(method: str, path: str, headers=None, json=None):
	"""Send a request to the Frappe WSGI app, as a real client would."""
	from frappe.app import application

	site = frappe.local.site
	result = {}

	def run():
		result["response"] = Client(application).open(
			path, method=method, base_url=f"http://{site}", headers=headers or {}, json=json
		)

	thread = Thread(target=run)
	thread.start()
	thread.join()
	return result["response"]


class TestDonationAPIOverHTTP(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_project(CODE)
		client = make_api_client(CLIENT_NAME, "Online Store")
		user = frappe.get_doc("User", client.integration_user)
		user.api_key, user.api_secret = KEY, SECRET
		user.save(ignore_permissions=True)
		cls.client_name = client.name
		cls.user = client.integration_user
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Donation", {"api_client": cls.client_name})
		frappe.db.delete("Donation", {"project": CODE})
		frappe.delete_doc("Donation API Client", cls.client_name, force=True, ignore_permissions=True)
		frappe.delete_doc("User", cls.user, force=True, ignore_permissions=True)
		frappe.delete_doc("Donation Project", CODE, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def body(self, **overrides):
		data = {
			"external_reference": reference(),
			"project_code": CODE,
			"amount": 250.00,
			"paid_at": iso_ago(),
			"payment_reference": reference("pay"),
		}
		data.update(overrides)
		return data

	def test_valid_key_creates_then_replays(self):
		headers = {"Authorization": f"token {KEY}:{SECRET}"}
		payload = self.body()
		path = "/api/method/ataa_hub.api.v1.create_donation"

		first = http("POST", path, headers, payload)
		second = http("POST", path, headers, payload)

		self.assertEqual(first.status_code, 201, first.get_data(as_text=True))
		self.assertEqual(second.status_code, 200)
		self.assertTrue(second.get_json()["message"]["data"]["duplicate"])

	def test_wrong_key_is_401(self):
		response = http(
			"POST",
			"/api/method/ataa_hub.api.v1.create_donation",
			{"Authorization": "token wrong_key:wrong_secret"},
			self.body(),
		)
		self.assertEqual(response.status_code, 401)

	def test_missing_key_is_401(self):
		response = http("GET", "/api/method/ataa_hub.api.v1.list_projects")
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["message"]["error"]["code"], "AUTH_REQUIRED")

	def test_create_with_get_is_rejected(self):
		response = http(
			"GET", "/api/method/ataa_hub.api.v1.create_donation", {"Authorization": f"token {KEY}:{SECRET}"}
		)
		self.assertGreaterEqual(response.status_code, 400)
