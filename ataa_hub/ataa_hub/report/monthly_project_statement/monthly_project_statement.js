frappe.query_reports["Monthly Project Statement"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.month_end() },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
	],
};
