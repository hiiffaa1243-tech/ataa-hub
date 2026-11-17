frappe.query_reports["Donations by Project and Channel"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{
			fieldname: "channel",
			label: __("Channel"),
			fieldtype: "Select",
			options: ["", "Website", "Online Store", "POS", "Bank Transfer", "Partner"],
		},
	],
};
