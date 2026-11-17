frappe.ui.form.on("Donation", {
	setup(frm) {
		// Only projects that accept donations (PRD §5.1)
		frm.set_query("project", () => ({
			filters: { status: "Open", is_active: "Yes", is_public: 1, fund_type: ["is", "set"] },
		}));
		frm.set_query("donor", () => ({ filters: { customer_group: "Donors" } }));
	},

	refresh(frm) {
		const colors = { "Awaiting Payment": "orange", Paid: "green", Failed: "red", Refunded: "darkgrey" };
		if (!frm.is_new()) {
			frm.page.set_indicator(__(frm.doc.payment_status), colors[frm.doc.payment_status] || "gray");
		}

		// Manual entry is for bank transfers only; other channels come from integrations.
		frm.set_df_property("channel", "read_only", frm.is_new() ? 0 : 1);
		if (frm.is_new() && frm.doc.channel !== "Bank Transfer") {
			frm.set_value("channel", "Bank Transfer");
		}

		if (frm.doc.docstatus === 0 && frm.doc.channel === "Bank Transfer" && !frm.is_new()) {
			frm.set_intro(
				__("بعد ظهور الحوالة في كشف الحساب: أرفقي الإثبات ثم اضغطي «اعتماد» ليُسجَّل القيد المحاسبي."),
				"blue"
			);
		}

		if (frm.doc.journal_entry) {
			frm.add_custom_button(__("القيد المحاسبي"), () =>
				frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry)
			);
			frm.add_custom_button(__("دفتر الأستاذ"), () =>
				frappe.set_route("query-report", "General Ledger", {
					company: frm.doc.company,
					voucher_no: frm.doc.journal_entry,
					from_date: frm.doc.posting_date,
					to_date: frm.doc.posting_date,
				})
			);
		}
	},

	before_cancel(frm) {
		if (!(frm.doc.cancel_reason || "").trim()) {
			frappe.throw(__("اكتبي سبب الإلغاء في قسم «الإلغاء» واحفظي، ثم ألغي التبرع."));
		}
	},
});
