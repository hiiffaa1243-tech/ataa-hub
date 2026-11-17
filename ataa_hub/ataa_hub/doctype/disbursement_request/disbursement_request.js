frappe.ui.form.on("Disbursement Request", {
	setup(frm) {
		// The permission hook already limits a Project Manager to their own projects
		frm.set_query("project", () => ({ filters: { status: ["in", ["Active", "Completed"]] } }));
	},

	refresh(frm) {
		frm.trigger("show_balance");

		if (frm.doc.workflow_state === "Pending Executive Approval" && !frm.doc.rejection_reason) {
			frm.set_intro(__("للرفض: اكتب سبب الرفض واحفظ أولاً، ثم اختر «رفض» من قائمة الإجراءات."), "blue");
		}
	},

	project(frm) {
		frm.trigger("show_balance");
	},

	show_balance(frm) {
		if (!frm.doc.project) return;
		frappe.db
			.get_value("Donation Project", frm.doc.project, ["available_balance", "collected_amount", "disbursed_amount"])
			.then(({ message }) => {
				if (!message) return;
				frm.dashboard.clear_headline();
				frm.dashboard.set_headline(
					__("رصيد المشروع المتاح: {0} — المحصّل {1}، المصروف {2}", [
						format_currency(message.available_balance, "SAR"),
						format_currency(message.collected_amount, "SAR"),
						format_currency(message.disbursed_amount, "SAR"),
					]),
					flt(message.available_balance) >= flt(frm.doc.amount) ? "green" : "orange"
				);
			});
	},
});
