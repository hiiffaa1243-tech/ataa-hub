frappe.query_reports["Event Performance"] = {
	filters: [
		{ fieldname: "event", label: __("Fundraising Event"), fieldtype: "Link", options: "Fundraising Event", reqd: 1 },
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: ["Hour", "Terminal", "Card Scheme"],
			default: "Hour",
		},
	],
};
