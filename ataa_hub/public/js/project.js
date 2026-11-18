// Project form (staff only): target, collected, committed and available, read from the GL.
// The public site hides targets; this is where staff follow them.
frappe.ui.form.on("Project", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.fund_type) return;
		frappe
			.call("ataa_hub.accounting.get_project_balance_for_form", { project: frm.doc.name })
			.then(({ message: b }) => {
				if (!b) return;
				const money = (v) => format_currency(v || 0, "SAR", 0);
				const pct = b.progress_percent;
				const stats = [
					[__("المستهدف"), b.target_amount ? money(b.target_amount) : "—"],
					[__("المحصّل من التبرعات"), money(b.donation_income)],
					[__("محجوز لطلبات صرف"), money(b.committed)],
					[__("المتاح للصرف"), money(b.available)],
				];
				const bar =
					pct === null || pct === undefined
						? ""
						: `<div class="ataa-progress-track"><div style="width:${Math.min(pct, 100)}%"></div></div>
						   <div class="ataa-progress-caption"><span>${__("نسبة الإنجاز")}</span><b>${pct.toFixed(0)}%</b></div>`;
				const html = `<div class="ataa-progress-panel">${stats
					.map(([l, v]) => `<div class="ataa-stat"><span>${l}</span><b>${v}</b></div>`)
					.join("")}</div>${bar}`;
				frm.dashboard.add_section(html, __("الوضع المالي للمشروع"));
				frm.dashboard.show();
			});
	},
});
