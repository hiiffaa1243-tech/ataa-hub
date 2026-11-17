// Fund Allocation form: only unrestricted → restricted, live balance of the source fund.
frappe.ui.form.on("Fund Allocation", {
	setup(frm) {
		frm.set_query("from_project", () => ({ filters: { fund_type: "Unrestricted" } }));
		frm.set_query("to_project", () => ({ filters: { fund_type: "Restricted", status: ["!=", "Cancelled"] } }));
	},

	refresh(frm) {
		frm.trigger("from_project");
		if (frm.doc.journal_entry) {
			frm.add_custom_button(__("Journal Entry"), () =>
				frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry)
			);
		}
	},

	from_project(frm) {
		if (!frm.doc.from_project) return;
		frappe
			.call("ataa_hub.accounting.get_project_balance_for_form", { project: frm.doc.from_project })
			.then(({ message: b }) => {
				if (b) frm.dashboard.set_headline(__("General fund available: {0}", [format_currency(b.available, "SAR")]));
			});
	},
});
