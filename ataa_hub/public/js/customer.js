// Customer (donor): the Executive Director can grant Honorary membership by hand (PRD §7.5.5).
frappe.ui.form.on("Customer", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.honorary_since) return;
		if (!frappe.user.has_role("Executive Director") && !frappe.user.has_role("System Manager")) return;

		frm.add_custom_button(
			__("منح العضوية الفخرية"),
			() =>
				frappe.confirm(__("منح {0} العضوية الفخرية؟", [frm.doc.customer_name]), () =>
					frappe
						.call({
							method: "ataa_hub.memberships.grant_honorary",
							args: { customer: frm.doc.name },
							freeze: true,
						})
						.then(() => frm.reload_doc())
				),
			__("العضوية")
		);
	},
});
