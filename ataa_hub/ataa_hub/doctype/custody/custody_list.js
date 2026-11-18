frappe.listview_settings["Custody"] = {
	add_fields: ["status", "remaining"],
	get_indicator(doc) {
		const colors = { Requested: "orange", Rejected: "red", Open: "blue", "Closing Requested": "purple", Closed: "green" };
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
