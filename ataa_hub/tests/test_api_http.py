"""End-to-end through Frappe's real HTTP stack: Authorization header, JSON body, status codes.

Requests run in a separate thread with their own DB connection (like a real server),
so this class commits its fixtures. Names are random, so reruns never collide.
"""

from threading import Thread

import frappe
from frappe.tests import IntegrationTestCase
from werkzeug.test import Client

from ataa_hub.tests.factories import iso_ago, make_api_client, make_project, reference, unique

CREATE = "/api/method/ataa_hub.api.v1.create_donation"


def http(method: str, path: str, headers=None, json=None, query=None):
	"""Send a request to the Frappe WSGI app, as a real client would."""
	from frappe.app import application

	site = frappe.local.site
	result = {}

	def run():
		result["response"] = Client(application).open(
			path,
			method=method,
			base_url=f"http://{site}",
			headers=headers or {},
			json=json,
			query_string=query,
		)

	thread = Thread(target=run)
	thread.start()
	thread.join()
	return result["response"]


class TestDonationAPIOverHTTP(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.code = unique("HTTP")
		make_project(cls.code)
		client = make_api_client(unique("HTTP Store"), "Online Store")
		user = frappe.get_doc("User", client.integration_user)
		cls.key, cls.secret = frappe.generate_hash(length=15), frappe.generate_hash(length=15)
		user.api_key, user.api_secret = cls.key, cls.secret
		user.save(ignore_permissions=True)
		frappe.db.commit()

	def auth(self):
		return {"Authorization": f"token {self.key}:{self.secret}"}

	def body(self, **overrides):
		return {
			"external_reference": reference(),
			"project_code": self.code,
			"amount": 250.00,
			"paid_at": iso_ago(),
			"payment_reference": reference("pay"),
			"gift": {"recipient_name": "Test Recipient", "recipient_mobile": "+966500000001"},
			**overrides,
		}

	def test_valid_key_creates_posts_and_replays(self):
		payload = self.body()
		first = http("POST", CREATE, self.auth(), payload)
		second = http("POST", CREATE, self.auth(), payload)

		self.assertEqual(first.status_code, 201, first.get_data(as_text=True))
		self.assertEqual(second.status_code, 200)
		data = first.get_json()["message"]["data"]
		self.assertTrue(second.get_json()["message"]["data"]["duplicate"])
		self.assertIn("/gift/", data["gift"]["url"])
		self.assertEqual(data["status"], "Paid")

	def test_list_and_get(self):
		listed = http("GET", "/api/method/ataa_hub.api.v1.list_projects", self.auth())
		self.assertEqual(listed.status_code, 200)
		self.assertIn(self.code, {p["project_code"] for p in listed.get_json()["message"]["data"]})

		missing = http(
			"GET",
			"/api/method/ataa_hub.api.v1.get_donation",
			self.auth(),
			query={"external_reference": "NOPE"},
		)
		self.assertEqual(missing.status_code, 404)

	def test_wrong_key_is_401(self):
		response = http("POST", CREATE, {"Authorization": "token wrong_key:wrong_secret"}, self.body())
		self.assertEqual(response.status_code, 401)

	def test_missing_key_is_401(self):
		response = http("GET", "/api/method/ataa_hub.api.v1.list_projects")
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["message"]["error"]["code"], "AUTH_REQUIRED")

	def test_create_with_get_is_rejected(self):
		response = http("GET", CREATE, self.auth())
		self.assertGreaterEqual(response.status_code, 400)
