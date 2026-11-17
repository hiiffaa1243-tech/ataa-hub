frappe.ui.form.on("Donation Project", {
	refresh(frm) {
		if (frm.is_new()) return;

		const progress = Math.min(flt(frm.doc.progress_percent), 100);
		frm.dashboard.add_progress(
			__("نسبة الإنجاز"),
			progress,
			__("تم جمع {0} من {1}", [
				format_currency(frm.doc.collected_amount),
				format_currency(frm.doc.target_amount),
			])
		);

		frm.dashboard.add_indicator(
			__("الرصيد المتاح: {0}", [format_currency(frm.doc.available_balance)]),
			flt(frm.doc.available_balance) > 0 ? "green" : "orange"
		);

		if (frm.doc.status === "Active") {
			frm.add_custom_button(__("صفحة التبرع"), () => {
				window.open(`/donate/project?code=${encodeURIComponent(frm.doc.name)}`, "_blank");
			});
		}

		if (frappe.model.can_create("Disbursement Request")) {
			frm.add_custom_button(__("طلب صرف جديد"), () => {
				frappe.new_doc("Disbursement Request", { project: frm.doc.name });
			});
		}
	},
});
