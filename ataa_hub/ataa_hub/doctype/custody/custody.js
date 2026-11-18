// Custody (عهدة): action buttons by status and role, live totals while purchases are typed.

const CUSTODY_COLORS = {
	Requested: "orange",
	Rejected: "red",
	Open: "blue",
	"Closing Requested": "purple",
	Closed: "green",
};

frappe.ui.form.on("Custody", {
	setup(frm) {
		frm.set_query("project", () => ({ filters: { status: ["!=", "Cancelled"], fund_type: ["is", "set"] } }));
	},

	refresh(frm) {
		const s = frm.doc.status;
		const roles = frappe.user_roles;
		const accountant = roles.includes("Donations Accountant") || roles.includes("System Manager");
		const holder = frm.doc.holder === frappe.session.user;
		frm.page.set_indicator(__(s), CUSTODY_COLORS[s] || "gray");
		frm.set_df_property("expenses", "read_only", s !== "Open");
		frm.set_df_property("amount", "read_only", !frm.is_new() && s !== "Requested");
		frm.set_df_property("project", "read_only", !frm.is_new());
		frm.set_df_property("purpose", "read_only", !frm.is_new() && s !== "Requested");

		if (frm.is_new()) return;
		const call = (method, args, msg) =>
			frappe.call({ method: `ataa_hub.custody.${method}`, args: { name: frm.doc.name, ...args }, freeze: true }).then(() => {
				frappe.show_alert({ message: msg, indicator: "green" });
				frm.reload_doc();
			});

		if (accountant && s === "Requested") {
			frm.add_custom_button(__("اعتماد وصرف"), () =>
				frappe.confirm(
					`صرف عهدة بمبلغ <b>${format_currency(frm.doc.amount, "SAR")}</b> إلى ${frappe.utils.escape_html(frm.doc.holder_name || frm.doc.holder)}؟`,
					() => call("approve_and_pay", {}, "صُرفت العهدة")
				)
			).addClass("btn-primary ataa-btn-gold");
			frm.add_custom_button(__("رفض"), () =>
				frappe.prompt({ fieldname: "reason", fieldtype: "Small Text", label: "سبب الرفض", reqd: 1 }, (v) =>
					call("reject", { reason: v.reason }, "رُفض الطلب"), "رفض طلب العهدة", "رفض")
			);
		}
		if (s === "Open" && (holder || accountant)) {
			frm.add_custom_button(__("طلب إقفال العهدة"), () =>
				frappe.confirm("إرسال طلب إقفال العهدة للمحاسب؟", () => call("request_close", {}, "أُرسل طلب الإقفال"))
			);
		}
		if (accountant && (s === "Closing Requested" || s === "Open")) {
			frm.add_custom_button(__("إقفال العهدة وإصدار التقرير"), () =>
				frappe.confirm(
					`إقفال العهدة: مشتريات <b>${format_currency(frm.doc.spent, "SAR")}</b> تُقيَّد على المشروع، ومرتجع <b>${format_currency(frm.doc.remaining, "SAR")}</b> يعود للبنك. متابعة؟`,
					() => call("close", {}, "أُقفلت العهدة وصدر التقرير")
				)
			).addClass(s === "Closing Requested" ? "btn-primary ataa-btn-gold" : "");
		}
		if (s === "Closed" && frm.doc.report_file) {
			frm.add_custom_button(__("تقرير الإقفال"), () => window.open(frm.doc.report_file));
		}
		frm.add_custom_button(__("معاينة التقرير"), () => frm.print_doc());
		if (s === "Closing Requested" && accountant) {
			frm.dashboard.set_headline_alert(
				`<div class="text-center">طلب إقفال: هل تريد إقفال هذه العهدة؟</div>`
			);
		}
		render_progress(frm);
	},
	amount: (frm) => update_totals(frm),
});

frappe.ui.form.on("Custody Expense", {
	amount: (frm) => update_totals(frm),
	expenses_remove: (frm) => update_totals(frm),
});

function update_totals(frm) {
	const spent = (frm.doc.expenses || []).reduce((t, r) => t + flt(r.amount), 0);
	frm.set_value("spent", spent);
	frm.set_value("remaining", flt(frm.doc.amount) - spent);
}

function render_progress(frm) {
	if (frm.is_new() || !["Open", "Closing Requested", "Closed"].includes(frm.doc.status)) return;
	const pct = frm.doc.amount ? Math.min(100, (100 * flt(frm.doc.spent)) / frm.doc.amount) : 0;
	const missing = (frm.doc.expenses || []).filter((r) => !r.invoice).length;
	const money = (v) => format_currency(v || 0, "SAR");
	const stat = (l, v) => `<div class="ataa-stat"><span>${l}</span><b>${v}</b></div>`;
	const html = `<div class="ataa-custody-panel"><div class="ataa-progress-panel">
			${stat("مبلغ العهدة", money(frm.doc.amount))}${stat("المشتريات", money(frm.doc.spent))}
			${stat("المتبقي", money(frm.doc.remaining))}${stat("بلا فاتورة", missing)}
		</div>
		<div class="ataa-progress-track"><div style="width:${pct}%"></div></div>
		<div class="ataa-progress-caption"><span>نسبة الصرف</span><b>${pct.toFixed(0)}%</b></div></div>`;
	frm.dashboard.add_section(html, "وضع العهدة");
	frm.dashboard.show();
}
