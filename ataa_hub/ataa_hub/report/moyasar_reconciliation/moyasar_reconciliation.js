frappe.query_reports["Moyasar Reconciliation"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("من تاريخ"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -30),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("إلى تاريخ"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{ fieldname: "show_matched", label: __("إظهار المتطابق أيضاً"), fieldtype: "Check", default: 0 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "result_label" && data) {
			const color = data.result === "Matched" ? "green" : "red";
			value = `<span class="indicator-pill ${color}">${value}</span>`;
		}
		return value;
	},
};
