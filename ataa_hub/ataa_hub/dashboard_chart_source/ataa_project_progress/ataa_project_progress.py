"""Staff chart: target vs collected per restricted project (the public site hides targets)."""

import frappe

from ataa_hub.accounting import get_project_balance
from ataa_hub.constants import FUND_RESTRICTED


@frappe.whitelist()
def get(
	chart_name=None,
	chart=None,
	no_cache=None,
	filters=None,
	from_date=None,
	to_date=None,
	timespan=None,
	time_interval=None,
	heatmap_year=None,
):
	# Not cached on purpose: the result depends on the user (row permissions), and
	# frappe's cache_source caches per chart, not per user. A Project Manager only
	# sees their own projects here.
	projects = frappe.get_list(
		"Project",
		filters={"fund_type": FUND_RESTRICTED, "status": "Open", "target_amount": (">", 0)},
		fields=["name", "project_name", "public_title", "target_amount"],
		order_by="creation asc",
		limit=12,
	)
	labels, targets, collected = [], [], []
	for p in projects:
		labels.append(p.public_title or p.project_name)
		targets.append(p.target_amount)
		collected.append(get_project_balance(p.name).donation_income)
	return {
		"labels": labels,
		"datasets": [
			{"name": "المستهدف", "values": targets},
			{"name": "المحصّل", "values": collected},
		],
	}
