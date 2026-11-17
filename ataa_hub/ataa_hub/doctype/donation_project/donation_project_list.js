frappe.listview_settings["Donation Project"] = {
	add_fields: ["status", "progress_percent", "collected_amount", "target_amount"],

	get_indicator(doc) {
		const colors = { Draft: "gray", Active: "green", Completed: "blue", Closed: "darkgrey" };
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},

	formatters: {
		// Show a progress bar instead of a bare percentage in the list
		progress_percent(value) {
			const pct = Math.min(flt(value), 100);
			const color = pct >= 100 ? "var(--green-500)" : "var(--primary)";
			return `<div style="display:flex;align-items:center;gap:6px;min-width:120px">
				<div style="flex:1;height:8px;border-radius:4px;background:var(--gray-200);overflow:hidden">
					<div style="width:${pct}%;height:100%;background:${color}"></div>
				</div>
				<span>${flt(value, 1)}%</span>
			</div>`;
		},
	},
};
