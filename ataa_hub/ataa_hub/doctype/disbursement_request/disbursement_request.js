// Disbursement Request form: filters, live balance, link to the payment journal.
frappe.ui.form.on("Disbursement Request", {
	setup(frm) {
		frm.set_query("project", () => ({ filters: { status: ["!=", "Cancelled"], fund_type: ["is", "set"] } }));
		frm.set_query("expense_account", () => ({
			filters: { company: frm.doc.company, root_type: "Expense", is_group: 0 },
		}));
		frm.set_query("paid_from_account", () => ({
			filters: { company: frm.doc.company, account_type: ["in", ["Bank", "Cash"]], is_group: 0 },
		}));
	},

	refresh(frm) {
		frm.trigger("show_balance");
		if (frm.doc.journal_entry) {
			frm.add_custom_button(__("Journal Entry"), () =>
				frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry)
			);
		}
		if (frm.doc.workflow_state === "Pending Executive Approval") {
			frm.set_intro(__("To reject, write the reason in «Rejection Reason», save, then choose Reject."), "orange");
		}
	},

	project(frm) {
		frm.trigger("show_balance");
	},

	show_balance(frm) {
		if (!frm.doc.project) return;
		frappe
			.call("ataa_hub.accounting.get_project_balance_for_form", { project: frm.doc.project })
			.then(({ message: b }) => {
				if (!b) return;
				const fmt = (v) => format_currency(v, "SAR");
				frm.dashboard.set_headline(
					__("Balance {0} · Committed {1} · Available {2}", [fmt(b.balance), fmt(b.committed), fmt(b.available)])
				);
			});
	},
});
