"""M7: event live screen feed (PRD §7.3)."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, flt, now_datetime

from ataa_hub import events
from ataa_hub.public import event_feed
from ataa_hub.tests.factories import (
	make_api_client,
	make_event,
	make_integration_donation,
	make_project,
	unique,
)


class TestEventFeed(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.p1, cls.p2 = make_project().name, make_project().name
		cls.pos = make_api_client(unique("POS"), "POS", allowed=[cls.p1, cls.p2]).name

	def setUp(self):
		self.event = make_event(projects=[self.p1, self.p2], terminals=[(self.pos, "T01"), (self.pos, "T02")])
		self.event.db_set("live_screen_enabled", 1)
		events.clear_event_feed(self.event.name)

	def tearDown(self):
		frappe.set_user("Administrator")

	def pos_donation(self, project, amount, terminal="T01", hours_ago=0.1, **extra):
		return make_integration_donation(
			project,
			amount,
			channel="POS",
			api_client=self.pos,
			fundraising_event=self.event.name,
			terminal_id=terminal,
			card_scheme="mada",
			rrn=unique("RRN"),
			paid_at=add_to_date(now_datetime(), hours=-hours_ago),
			donor_name="اسم لا يجب أن يظهر",
			**extra,
		)

	def test_feed_totals(self):
		self.pos_donation(self.p1, 100, "T01")
		self.pos_donation(self.p1, 50, "T02")
		self.pos_donation(self.p2, 300, "T02", hours_ago=3)

		feed = events.build_event_feed(self.event.name)
		self.assertEqual((feed["total"], feed["count"], feed["last_hour"]), (450, 3, 150))
		self.assertEqual(feed["progress"], round(450 / 50000 * 100, 1))
		self.assertTrue(feed["open"])
		self.assertEqual({t["terminal"]: t["amount"] for t in feed["by_terminal"]}, {"T01": 100, "T02": 350})
		self.assertEqual([p["amount"] for p in feed["by_project"]], [300, 150])
		self.assertEqual([d["amount"] for d in feed["latest"]], [50, 100, 300])  # newest first

	def test_feed_has_no_donor_data(self):
		self.pos_donation(self.p1, 10)
		text = frappe.as_json(events.build_event_feed(self.event.name))
		self.assertNotIn("اسم لا يجب أن يظهر", text)
		self.assertNotIn("donor", text)

	def test_cancelled_and_other_events_are_not_counted(self):
		d = self.pos_donation(self.p1, 70)
		d.cancel_reason = "Test"
		d.save()
		d.cancel()
		self.assertEqual(events.build_event_feed(self.event.name)["total"], 0)

	def test_cache_is_cleared_on_submit(self):
		self.assertEqual(events.get_event_feed(self.event.name)["total"], 0)  # now cached
		self.pos_donation(self.p1, 25)
		self.assertEqual(events.get_event_feed(self.event.name)["total"], 25)

	def test_cached_between_donations(self):
		events.get_event_feed(self.event.name)
		with patch.object(events, "build_event_feed") as build:
			events.get_event_feed(self.event.name)
		build.assert_not_called()

	def test_staff_views_get_realtime_message(self):
		with patch("frappe.publish_realtime") as publish:
			self.pos_donation(self.p1, 40)
		ours = [c for c in publish.call_args_list if c.args and c.args[0] == events.REALTIME_EVENT]
		self.assertEqual(len(ours), 1)
		self.assertEqual(ours[0].args[1]["amount"], 40)
		self.assertTrue(ours[0].kwargs.get("after_commit"))

	def test_guest_endpoint_and_disabled_screen(self):
		frappe.set_user("Guest")
		self.assertEqual(event_feed(self.event.name.lower())["event_code"], self.event.name)
		self.assertEqual(event_feed("NO-SUCH-EVENT"), {"error": "not_found"})
		frappe.set_user("Administrator")

		self.event.db_set("live_screen_enabled", 0)
		events.clear_event_feed(self.event.name)
		self.assertIsNone(events.get_event_feed(self.event.name))

	def test_event_page_renders(self):
		from frappe.utils import set_request
		from frappe.website.serve import get_response

		self.pos_donation(self.p1, 15)
		frappe.set_user("Guest")
		set_request(method="GET", path=f"/event/{self.event.name}")
		response = get_response()
		self.assertEqual(response.status_code, 200)
		html = response.get_data(as_text=True)
		self.assertIn(self.event.event_name, html)
		self.assertIn("ATAA_EVENT_FEED", html)
		self.assertNotIn("اسم لا يجب أن يظهر", html)
		self.assertEqual(flt(events.get_event_feed(self.event.name)["total"]), 15)
