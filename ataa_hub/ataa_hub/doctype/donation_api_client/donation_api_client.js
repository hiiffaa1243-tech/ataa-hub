frappe.ui.form.on("Donation API Client", {
	refresh(frm) {
		frm.page.set_indicator(
			frm.doc.is_active ? __("نشط") : __("موقوف"),
			frm.doc.is_active ? "green" : "red"
		);

		if (frm.is_new() || !frappe.user.has_role("System Manager")) return;

		frm.add_custom_button(__("توليد مفتاح الربط"), () => {
			frappe.confirm(
				__("سيُولَّد سر جديد، وأي سر قديم سيتوقف عن العمل فوراً. متابعة؟"),
				() => frm.call("generate_keys").then(({ message }) => show_keys(message))
			);
		}).addClass("btn-primary");

		frm.add_custom_button(__("توثيق الـ API"), () => window.open("/api-docs", "_blank"));
	},
});

function show_keys({ api_key, api_secret }) {
	const header = `token ${api_key}:${api_secret}`;
	const d = new frappe.ui.Dialog({
		title: __("مفتاح الربط"),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted">${__(
					"انسخي القيم الآن وأرسليها لمسؤول المتجر بطريقة آمنة. السر لن يظهر مرة أخرى."
				)}</p>`,
			},
			{ fieldtype: "Data", label: "api_key", default: api_key, read_only: 1 },
			{ fieldtype: "Data", label: "api_secret", default: api_secret, read_only: 1 },
			{ fieldtype: "Code", label: "Authorization header", default: header, read_only: 1 },
		],
		primary_action_label: __("نسخ الترويسة"),
		primary_action() {
			frappe.utils.copy_to_clipboard(header);
		},
	});
	d.show();
}
