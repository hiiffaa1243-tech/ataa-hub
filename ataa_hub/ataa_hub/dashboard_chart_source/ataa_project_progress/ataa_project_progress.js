frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Ataa Project Progress"] = {
	method: "ataa_hub.ataa_hub.dashboard_chart_source.ataa_project_progress.ataa_project_progress.get",
	filters: [],
};
