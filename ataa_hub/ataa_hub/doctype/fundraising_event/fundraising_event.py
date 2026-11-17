"""Fundraising Event: a booth or campaign with its own projects and POS terminals (PRD §7.3).

The API checks donations that carry `event_code` against this record:
status Active, `paid_at` inside the time window, the (API client, terminal) pair
listed here, and the project listed here. The live screen arrives in M7.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime

from ataa_hub.constants import CHANNEL_POS

EVENT_ACTIVE = "Active"


class FundraisingEvent(Document):
	def validate(self):
		self.event_code = (self.event_code or "").strip().upper()
		if get_datetime(self.end_datetime) <= get_datetime(self.start_datetime):
			frappe.throw(_("وقت نهاية الفعالية يجب أن يكون بعد وقت بدايتها."))

		projects = [row.project for row in self.projects]
		if len(projects) != len(set(projects)):
			frappe.throw(_("يوجد مشروع مكرر في قائمة مشاريع الفعالية."))

		seen = set()
		for row in self.terminals:
			row.terminal_id = (row.terminal_id or "").strip()
			key = (row.api_client, row.terminal_id)
			if key in seen:
				frappe.throw(_("الجهاز {0} مكرر في الفعالية.").format(row.terminal_id))
			seen.add(key)
			if frappe.db.get_value("Donation API Client", row.api_client, "channel") != CHANNEL_POS:
				frappe.throw(
					_("الصف {0}: عميل الربط {1} ليس جهاز نقاط بيع.").format(
						row.idx, frappe.bold(row.api_client)
					)
				)

	@property
	def project_names(self) -> set[str]:
		return {row.project for row in self.projects}

	def is_open_at(self, moment) -> bool:
		moment = get_datetime(moment)
		return self.status == EVENT_ACTIVE and get_datetime(self.start_datetime) <= moment <= get_datetime(
			self.end_datetime
		)

	def has_terminal(self, api_client: str, terminal_id: str | None) -> bool:
		return any(r.api_client == api_client and r.terminal_id == terminal_id for r in self.terminals)
