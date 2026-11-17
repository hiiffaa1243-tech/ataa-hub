frappe.listview_settings["Donation"] = {
	add_fields: ["status", "channel"],
	get_indicator(doc) {
		const colors = { Pending: "orange", Paid: "green", Failed: "red", Refunded: "darkgrey" };
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
};
