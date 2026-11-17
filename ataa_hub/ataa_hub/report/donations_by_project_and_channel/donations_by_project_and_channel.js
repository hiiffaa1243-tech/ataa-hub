frappe.query_reports["Donations by Project and Channel"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("من تاريخ"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -12),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("إلى تاريخ"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{ fieldname: "project", label: __("المشروع"), fieldtype: "Link", options: "Donation Project" },
		{
			fieldname: "channel",
			label: __("القناة"),
			fieldtype: "Select",
			options: ["", "Website", "Online Store", "POS", "Bank Transfer", "Partner"],
		},
	],
};
