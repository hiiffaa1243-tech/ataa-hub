frappe.listview_settings["Disbursement Request"] = {
	add_fields: ["workflow_state"],
	has_indicator_for_draft: 1,
	get_indicator(doc) {
		const colors = {
			Draft: "gray",
			"Pending Accountant Review": "orange",
			"Pending Executive Approval": "yellow",
			Approved: "blue",
			Rejected: "red",
			Disbursed: "green",
		};
		const state = doc.workflow_state || "Draft";
		return [__(state), colors[state] || "gray", "workflow_state,=," + state];
	},
};
