frappe.ui.form.on("Donation", {
	setup(frm) {
		// Only active projects can receive a new donation
		frm.set_query("project", () => ({ filters: { status: "Active" } }));
	},

	refresh(frm) {
		const colors = { Pending: "orange", Paid: "green", Failed: "red", Refunded: "darkgrey" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");

		// Accountant shortcut: confirm a bank transfer once it shows on the bank statement
		if (
			!frm.is_new() &&
			frm.doc.channel === "Bank Transfer" &&
			frm.doc.status === "Pending" &&
			frm.perm[0].write
		) {
			frm.add_custom_button(__("تأكيد وصول الحوالة"), () => {
				if (!frm.doc.transfer_proof) {
					frappe.msgprint(__("أرفقي إثبات التحويل أولاً."));
					return;
				}
				frm.set_value("status", "Paid");
				frm.save();
			}).addClass("btn-primary");
		}
	},
});
