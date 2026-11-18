// Staff home (لوحة التحكم): one page per role, built only from our own whitelisted
// methods (ataa_hub.staff_dashboard) and standard Frappe UI pieces. No ERPNext code touched.

frappe.pages["ataa-home"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: "لوحة التحكم", single_column: true });
	wrapper.ataa = new AtaaDashboard(page);
};

frappe.pages["ataa-home"].on_page_show = function (wrapper) {
	wrapper.ataa && wrapper.ataa.load();
};

const ATAA_STATES = {
	Draft: ["مسودة", "gray"],
	"Pending Accountant Review": ["بانتظار المحاسب", "orange"],
	"Pending Executive Approval": ["بانتظار المدير التنفيذي", "blue"],
	Approved: ["معتمد — بانتظار الصرف", "teal"],
	Rejected: ["مرفوض", "red"],
	Paid: ["مصروف", "green"],
	Requested: ["طلب جديد", "orange"],
	Open: ["مفتوحة", "blue"],
	"Closing Requested": ["طلب إقفال", "purple"],
	Closed: ["مقفلة", "green"],
};
const ATAA_CHANNELS = {
	Website: "الموقع",
	"Online Store": "المتجر",
	POS: "نقاط البيع",
	"Bank Transfer": "تحويل بنكي",
	Partner: "شريك",
};

class AtaaDashboard {
	constructor(page) {
		this.page = page;
		this.$body = $('<div class="ataa-dash"></div>').appendTo(page.main);
		page.set_secondary_action("تحديث", () => this.load(), "refresh");
		this.bind();
	}

	// ---------------------------------------------------------------- helpers
	esc(v) {
		return frappe.utils.escape_html(v == null ? "" : String(v));
	}
	money(v, digits = 0) {
		return format_currency(v || 0, "SAR", digits);
	}
	pill(state) {
		const [label, color] = ATAA_STATES[state] || [state, "gray"];
		return `<span class="ataa-pill ataa-pill-${color}">${label}</span>`;
	}
	ago(d) {
		return d ? frappe.datetime.comment_when(d) : "";
	}
	bar(pct) {
		const w = Math.max(0, Math.min(100, pct || 0));
		return `<div class="ataa-bar"><i style="width:${w}%"></i></div>`;
	}
	kpi(label, value, sub = "", tone = "") {
		return `<div class="ataa-kpi ${tone}"><span>${label}</span><b>${value}</b>${sub ? `<small>${sub}</small>` : ""}</div>`;
	}
	section(title, body, extra = "", cls = "") {
		return `<section class="ataa-card ${cls}"><header><h3>${title}</h3><div>${extra}</div></header>${body}</section>`;
	}
	empty(text) {
		return `<div class="ataa-empty">${text}</div>`;
	}
	link(doctype, name, label) {
		return `<a href="/desk/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}">${this.esc(label || name)}</a>`;
	}
	greeting() {
		const h = new Date().getHours();
		return h < 12 ? "صباح الخير" : "مساء الخير";
	}

	// ---------------------------------------------------------------- load
	load() {
		return frappe.call("ataa_hub.staff_dashboard.get_dashboard").then(({ message: d }) => {
			this.d = d;
			const roleLabel = { executive: "المدير التنفيذي", accountant: "المحاسب", pm: "مدير المشاريع" }[d.view];
			const hero = `<div class="ataa-hero">
				<div><h2>${this.greeting()}، ${this.esc(d.full_name)}</h2>
				<p>${roleLabel} · ${frappe.datetime.str_to_user(frappe.datetime.get_today())}</p></div>
				<div class="ataa-hero-actions"></div></div>`;
			this.$body.html(hero + this[d.view]());
		});
	}

	actions(buttons) {
		const $a = this.$body.find(".ataa-hero-actions");
		buttons.forEach(([label, fn, primary]) => {
			$(`<button class="btn ${primary ? "btn-primary ataa-btn-gold" : "btn-default"}">${label}</button>`)
				.on("click", fn)
				.appendTo($a);
		});
	}

	// ---------------------------------------------------------------- shared blocks
	projectCards(projects, withActions) {
		if (!projects.length) return this.empty("لا توجد مشاريع بعد.");
		return `<div class="ataa-projects">${projects
			.map((p) => {
				const img = p.public_image
					? `<div class="ataa-pimg" style="background-image:url('${encodeURI(p.public_image)}')"></div>`
					: `<div class="ataa-pimg ataa-pimg-empty">${this.esc((p.title || "").slice(0, 1))}</div>`;
				const pct = p.progress == null ? null : p.progress;
				const target = p.target
					? `<div class="ataa-target"><div class="ataa-target-row"><span>المحصّل ${this.money(p.collected)}</span><span>المستهدف ${this.money(p.target)}</span></div>
						${this.bar(pct)}<div class="ataa-target-pct">${(pct || 0).toFixed(0)}%</div></div>`
					: `<div class="ataa-target ataa-muted">بدون مستهدف · المحصّل ${this.money(p.collected)}</div>`;
				const btns = withActions
					? `<div class="ataa-pactions">
						<button class="btn btn-xs btn-default" data-act="dr" data-project="${this.esc(p.name)}">طلب صرف</button>
						<button class="btn btn-xs btn-default" data-act="cus" data-project="${this.esc(p.name)}">طلب عهدة</button>
						<a class="btn btn-xs btn-default" href="/desk/project/${encodeURIComponent(p.name)}">التفاصيل</a></div>`
					: "";
				return `<article class="ataa-project">
					${img}
					<div class="ataa-pbody">
						<div class="ataa-ptitle"><b>${this.esc(p.title)}</b>
							<span class="ataa-chip">${this.esc(p.project_code || "")}</span>
							<span class="ataa-chip ${p.fund_type === "Restricted" ? "gold" : ""}">${p.fund_type === "Restricted" ? "مقيّد" : "عام"}</span>
							${p.is_public ? "" : '<span class="ataa-chip">غير منشور</span>'}</div>
						${target}
						<div class="ataa-pstats">
							<div><span>المتاح للصرف</span><b>${this.money(p.available)}</b></div>
							<div><span>محجوز</span><b>${this.money(p.committed)}</b></div>
							<div><span>آخر 30 يوماً</span><b>${this.money(p.last30)}</b><small>${p.last30_count} تبرع</small></div>
						</div>
						${btns}
					</div></article>`;
			})
			.join("")}</div>`;
	}

	projectTable(projects) {
		if (!projects.length) return this.empty("لا توجد مشاريع.");
		return `<div class="ataa-table"><table><thead><tr><th>المشروع</th><th>المستهدف</th><th>المحصّل</th><th>الإنجاز</th><th>المتاح</th><th>آخر 30 يوماً</th></tr></thead><tbody>${projects
			.map(
				(p) => `<tr><td>${this.link("Project", p.name, p.title)}</td><td>${p.target ? this.money(p.target) : "—"}</td>
				<td>${this.money(p.collected)}</td><td class="ataa-td-bar">${p.target ? this.bar(p.progress) + `<small>${(p.progress || 0).toFixed(0)}%</small>` : "—"}</td>
				<td>${this.money(p.available)}</td><td>${this.money(p.last30)}</td></tr>`
			)
			.join("")}</tbody></table></div>`;
	}

	requestList(rows, buttons) {
		if (!rows.length) return this.empty("لا يوجد شيء هنا الآن.");
		return `<div class="ataa-list">${rows
			.map(
				(r) => `<div class="ataa-row">
					<div class="ataa-row-main">
						<div class="ataa-row-title">${this.link("Disbursement Request", r.name, r.purpose)} ${this.pill(r.workflow_state)}</div>
						<div class="ataa-row-sub">${this.esc(r.project_title || r.project)} · ${this.esc(r.name)} · ${this.ago(r.creation)}</div>
					</div>
					<div class="ataa-row-amount">${this.money(r.amount, 2)}</div>
					<div class="ataa-row-btns">${(buttons || [])
						.map(([label, action, cls]) => `<button class="btn btn-xs ${cls || "btn-default"}" data-wf="Disbursement Request" data-name="${this.esc(r.name)}" data-action="${action}">${label}</button>`)
						.join("")}</div>
				</div>`
			)
			.join("")}</div>`;
	}

	allocationList(rows, buttons) {
		if (!rows.length) return "";
		return `<div class="ataa-list">${rows
			.map(
				(r) => `<div class="ataa-row">
					<div class="ataa-row-main">
						<div class="ataa-row-title">${this.link("Fund Allocation", r.name, "تخصيص إلى " + (r.to_project_title || r.to_project))} ${this.pill(r.workflow_state)}</div>
						<div class="ataa-row-sub">${this.esc(r.reason)} · ${this.ago(r.creation)}</div>
					</div>
					<div class="ataa-row-amount">${this.money(r.amount, 2)}</div>
					<div class="ataa-row-btns">${(buttons || [])
						.map(([label, action, cls]) => `<button class="btn btn-xs ${cls || "btn-default"}" data-wf="Fund Allocation" data-name="${this.esc(r.name)}" data-action="${action}">${label}</button>`)
						.join("")}</div>
				</div>`
			)
			.join("")}</div>`;
	}

	custodyList(rows, mode) {
		if (!rows.length) return this.empty("لا توجد عهد.");
		return `<div class="ataa-list">${rows
			.map((c) => {
				const pct = c.amount ? (100 * (c.spent || 0)) / c.amount : 0;
				let btns = "";
				if (mode === "accountant" && c.status === "Requested")
					btns = `<button class="btn btn-xs btn-primary ataa-btn-gold" data-cus="approve_and_pay" data-name="${this.esc(c.name)}">اعتماد وصرف</button>
						<button class="btn btn-xs btn-default" data-cus="reject" data-name="${this.esc(c.name)}">رفض</button>`;
				else if (mode === "accountant" && c.status !== "Closed")
					btns = `<button class="btn btn-xs ${c.status === "Closing Requested" ? "btn-primary ataa-btn-gold" : "btn-default"}" data-cus="close" data-name="${this.esc(c.name)}">إقفال وإصدار التقرير</button>`;
				else if (mode === "pm" && c.status === "Open")
					btns = `<a class="btn btn-xs btn-primary ataa-btn-gold" href="/desk/custody/${encodeURIComponent(c.name)}">تسجيل مشتريات</a>`;
				if (c.report_file) btns += `<a class="btn btn-xs btn-default" target="_blank" href="${encodeURI(c.report_file)}">التقرير</a>`;
				const progress =
					c.status === "Requested"
						? ""
						: `<div class="ataa-cus-progress">${this.bar(pct)}<small>صُرف ${this.money(c.spent, 2)} · متبقٍ ${this.money(c.remaining, 2)}</small></div>`;
				return `<div class="ataa-row ${c.status === "Closing Requested" ? "ataa-row-alert" : ""}">
					<div class="ataa-row-main">
						<div class="ataa-row-title">${this.link("Custody", c.name, c.purpose)} ${this.pill(c.status)}</div>
						<div class="ataa-row-sub">${this.esc(c.holder_name || c.holder)} · ${this.esc(c.project_title || c.project)} · ${this.ago(c.creation)}</div>
						${progress}
					</div>
					<div class="ataa-row-amount">${this.money(c.amount, 2)}</div>
					<div class="ataa-row-btns">${btns}</div>
				</div>`;
			})
			.join("")}</div>`;
	}

	donationList(rows) {
		if (!rows.length) return this.empty("لا توجد تبرعات بعد.");
		return `<div class="ataa-list ataa-list-compact">${rows
			.map(
				(r) => `<div class="ataa-row"><div class="ataa-row-main">
					<div class="ataa-row-title">${this.link("Donation", r.name, r.donor_name || "متبرع")} ${r.is_gift ? '<span class="ataa-chip gold">إهداء</span>' : ""}</div>
					<div class="ataa-row-sub">${this.esc(r.project_title)} · ${ATAA_CHANNELS[r.channel] || this.esc(r.channel)} · ${frappe.datetime.str_to_user(r.posting_date)}</div></div>
					<div class="ataa-row-amount">${this.money(r.amount, 2)}</div></div>`
			)
			.join("")}</div>`;
	}

	// ---------------------------------------------------------------- Project manager
	pm() {
		const d = this.d;
		const ps = d.projects;
		const sum = (k) => ps.reduce((t, p) => t + (p[k] || 0), 0);
		const openReq = d.requests.filter((r) => !["Paid", "Rejected"].includes(r.workflow_state)).length;
		const openCus = d.custody.filter((c) => ["Open", "Closing Requested"].includes(c.status));
		setTimeout(() =>
			this.actions([
				["+ إضافة مشروع", () => this.newProject(), true],
				["طلب صرف", () => this.newRequest()],
				["طلب عهدة", () => this.newCustody()],
			])
		);
		return `<div class="ataa-kpis">
				${this.kpi("مشاريعي", ps.length)}
				${this.kpi("المحصّل", this.money(sum("collected")), "من التبرعات", "gold")}
				${this.kpi("المتاح للصرف", this.money(sum("available")))}
				${this.kpi("آخر 30 يوماً", this.money(sum("last30")), ps.reduce((t, p) => t + p.last30_count, 0) + " تبرع")}
				${this.kpi("طلبات صرف مفتوحة", openReq, "", openReq ? "warn" : "")}
				${this.kpi("عهد مفتوحة", this.money(openCus.reduce((t, c) => t + c.remaining, 0)), openCus.length + " عهدة · المتبقي")}
			</div>
			${this.section("مشاريعي — المستهدف والمحصّل", this.projectCards(ps, true))}
			<div class="ataa-grid-2">
				${this.section("طلبات الصرف", this.requestList(d.requests) + this.allocationList(d.allocations), `<a href="/desk/disbursement-request">الكل</a>`)}
				${this.section("عهدي", this.custodyList(d.custody, "pm"), `<a href="/desk/custody">الكل</a>`)}
			</div>
			${this.section("أحدث التبرعات على مشاريعي", this.donationList(d.donations), `<a href="/desk/donation">الكل</a>`)}`;
	}

	// ---------------------------------------------------------------- Executive director
	executive() {
		const d = this.d;
		const k = d.kpis;
		const waiting = d.approvals.length + d.allocation_approvals.length;
		const wfButtons = [
			["اعتماد", "Approve", "btn-primary ataa-btn-gold"],
			["رفض", "Reject", "btn-default"],
		];
		setTimeout(() =>
			this.actions([
				[`طلبات الصرف${waiting ? ` (${waiting})` : ""}`, () => this.scrollTo(".ataa-approvals"), true],
				["تقرير المشاريع الشهري", () => frappe.set_route("query-report", "Monthly Project Statement")],
				["تقرير الأثر", () => frappe.set_route("query-report", "Impact Report")],
			])
		);
		return `<div class="ataa-kpis">
				${this.kpi("تبرعات هذا الشهر", this.money(k.donations_month), "", "gold")}
				${this.kpi("بانتظار موافقتك", waiting, "طلب", waiting ? "warn" : "")}
				${this.kpi("رصيد المشاريع المقيّدة", this.money(k.restricted))}
				${this.kpi("رصيد الصندوق العام", this.money(k.unrestricted))}
				${this.kpi("الأعضاء النشطون", k.active_members, this.money(k.membership_revenue) + " سنوياً")}
				${this.kpi("عهد لدى الموظفين", this.money(k.open_custody))}
			</div>
			${this.section(
				`بانتظار موافقتك <span class="ataa-count">${waiting}</span>`,
				waiting
					? this.requestList(d.approvals, wfButtons) + this.allocationList(d.allocation_approvals, wfButtons)
					: this.empty("لا توجد طلبات بانتظارك 🎉"),
				`<a href="/desk/disbursement-request?workflow_state=Pending%20Executive%20Approval">عرض في القائمة</a>`,
				"ataa-approvals"
			)}
			${this.section("المشاريع — المستهدف والمحصّل", this.projectTable(d.projects))}
			<div class="ataa-grid-2">
				${this.section("آخر طلبات الصرف", this.requestList(d.recent_requests), `<a href="/desk/disbursement-request">الكل</a>`)}
				${this.section("أحدث التبرعات", this.donationList(d.donations), `<a href="/desk/donation">الكل</a>`)}
			</div>
			${this.section("العهد", this.custodyList(d.custody, "view"), `<a href="/desk/custody">الكل</a>`)}`;
	}

	// ---------------------------------------------------------------- Accountant
	accountant() {
		const d = this.d;
		const k = d.kpis;
		const requested = d.custody.filter((c) => c.status === "Requested");
		const open = d.custody.filter((c) => ["Open", "Closing Requested"].includes(c.status));
		const closed = d.custody.filter((c) => c.status === "Closed");
		const closing = open.filter((c) => c.status === "Closing Requested").length;
		setTimeout(() =>
			this.actions([
				["العهد", () => this.scrollTo(".ataa-custody"), true],
				["مطابقة ميسّر", () => frappe.set_route("query-report", "Moyasar Reconciliation")],
				["دفتر الأستاذ", () => frappe.set_route("query-report", "General Ledger")],
			])
		);
		return `<div class="ataa-kpis">
				${this.kpi("طلبات عهد جديدة", requested.length, "", requested.length ? "warn" : "")}
				${this.kpi("عهد مفتوحة", this.money(open.reduce((t, c) => t + c.amount, 0)), open.length + " عهدة" + (closing ? ` · ${closing} طلب إقفال` : ""), closing ? "warn" : "")}
				${this.kpi("طلبات صرف للمراجعة", k.to_review, "", k.to_review ? "warn" : "")}
				${this.kpi("معتمدة بانتظار الصرف", k.to_pay)}
				${this.kpi("تحويلات بنكية للتحقق", k.bank_transfers, "", k.bank_transfers ? "warn" : "")}
				${this.kpi("تبرعات هذا الشهر", this.money(k.donations_month), `${k.reconciliation || 0} فروقات مطابقة · ${k.charges || 0} عضويات للمتابعة`, "gold")}
			</div>
			<div class="ataa-grid-2 ataa-custody">
				${this.section(`طلبات العهد <span class="ataa-count">${requested.length}</span>`, this.custodyList(requested, "accountant"), `<a href="/desk/custody?status=Requested">الكل</a>`)}
				${this.section(`العهد المفتوحة <span class="ataa-count">${open.length}</span>`, this.custodyList(open, "accountant"), `<a href="/desk/custody">الكل</a>`)}
			</div>
			${closed.length ? this.section("عهد أُقفلت مؤخراً", this.custodyList(closed, "accountant"), `<a href="/desk/custody?status=Closed">الكل</a>`) : ""}
			<div class="ataa-grid-2">
				${this.section(
					"طلبات صرف للمراجعة",
					this.requestList(d.to_review, [
						["موافقة", "Approve", "btn-primary ataa-btn-gold"],
						["إرجاع", "Return", "btn-default"],
					])
				)}
				${this.section("معتمدة — بانتظار الصرف", this.requestList(d.to_pay, [["تم الصرف", "Mark Paid", "btn-primary ataa-btn-gold"]]))}
			</div>
			<div class="ataa-grid-2">
				${this.section("تحويلات بنكية للتحقق", this.transferList(d.bank_transfers), `<a href="/desk/donation?channel=Bank%20Transfer&docstatus=0">الكل</a>`)}
				${this.section("أحدث التبرعات", this.donationList(d.donations))}
			</div>
			${this.section("المشاريع", this.projectTable(d.projects))}`;
	}

	transferList(rows) {
		if (!rows.length) return this.empty("لا توجد تحويلات بانتظار التحقق.");
		return `<div class="ataa-list">${rows
			.map(
				(r) => `<div class="ataa-row"><div class="ataa-row-main">
					<div class="ataa-row-title">${this.link("Donation", r.name, r.donor_name || "متبرع")}</div>
					<div class="ataa-row-sub">${this.esc(r.project_title)} · ${frappe.datetime.str_to_user(r.posting_date)}</div></div>
					<div class="ataa-row-amount">${this.money(r.amount, 2)}</div>
					<div class="ataa-row-btns">${r.transfer_proof ? `<a class="btn btn-xs btn-default" target="_blank" href="${encodeURI(r.transfer_proof)}">الإيصال</a>` : ""}
					<a class="btn btn-xs btn-primary ataa-btn-gold" href="/desk/donation/${encodeURIComponent(r.name)}">تحقق</a></div></div>`
			)
			.join("")}</div>`;
	}

	scrollTo(sel) {
		const el = this.$body.find(sel).get(0);
		el && el.scrollIntoView({ behavior: "smooth", block: "start" });
	}

	// ---------------------------------------------------------------- events
	bind() {
		const me = this;
		this.$body.on("click", "[data-act]", function () {
			const project = $(this).data("project");
			$(this).data("act") === "dr" ? me.newRequest(project) : me.newCustody(project);
		});
		this.$body.on("click", "[data-wf]", function () {
			const $b = $(this);
			me.workflow($b.data("wf"), $b.data("name"), $b.data("action"));
		});
		this.$body.on("click", "[data-cus]", function () {
			me.custodyAction($(this).data("cus"), $(this).data("name"));
		});
	}

	done(msg) {
		frappe.show_alert({ message: msg, indicator: "green" });
		this.load();
	}

	workflow(doctype, name, action) {
		const run = (reason) =>
			frappe
				.call({ method: "ataa_hub.staff_dashboard.apply_action", args: { doctype, name, action, reason }, freeze: true })
				.then(() => this.done("تم"));
		if (action === "Reject" || action === "Return") {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: action === "Reject" ? "سبب الرفض" : "ملاحظة لمقدّم الطلب", reqd: action === "Reject" },
				(v) => run(v.reason),
				action === "Reject" ? "رفض الطلب" : "إرجاع الطلب",
				action === "Reject" ? "رفض" : "إرجاع"
			);
		} else {
			const label = { Approve: "اعتماد", "Mark Paid": "تأكيد الصرف" }[action] || action;
			frappe.confirm(`${label} الطلب ${this.esc(name)}؟`, () => run());
		}
	}

	custodyAction(method, name) {
		const run = (args = {}) =>
			frappe
				.call({ method: `ataa_hub.custody.${method}`, args: { name, ...args }, freeze: true })
				.then(() => this.done("تم"));
		const c = this.d.custody.find((x) => x.name === name) || {};
		if (method === "reject") {
			frappe.prompt({ fieldname: "reason", fieldtype: "Small Text", label: "سبب الرفض", reqd: 1 }, (v) => run({ reason: v.reason }), "رفض طلب العهدة", "رفض");
		} else if (method === "approve_and_pay") {
			frappe.confirm(`صرف عهدة <b>${this.money(c.amount, 2)}</b> إلى ${this.esc(c.holder_name || c.holder)}؟ يُسجَّل قيد الصرف من البنك.`, () => run());
		} else if (method === "close") {
			frappe.confirm(
				`هل تريد إقفال العهدة ${this.esc(name)}؟<br>المشتريات <b>${this.money(c.spent, 2)}</b> تُقيَّد مصروفاً على المشروع، والمتبقي <b>${this.money(c.remaining, 2)}</b> يعود للبنك، ويصدر تقرير بكل المشتريات وفواتيرها.`,
				() => run()
			);
		}
	}

	// ---------------------------------------------------------------- dialogs
	projectOptions() {
		return this.d.projects.filter((p) => p.status === "Open").map((p) => ({ label: p.title, value: p.name }));
	}

	newProject() {
		const d = new frappe.ui.Dialog({
			title: "إضافة مشروع جديد",
			size: "large",
			fields: [
				{ fieldtype: "Section Break", label: "البيانات الأساسية" },
				{ fieldname: "project_name", fieldtype: "Data", label: "اسم المشروع", reqd: 1 },
				{ fieldname: "project_code", fieldtype: "Data", label: "رمز المشروع", reqd: 1, description: "حروف إنجليزية وأرقام، مثل WATER-06" },
				{ fieldtype: "Column Break" },
				{ fieldname: "fund_type", fieldtype: "Select", label: "نوع الصندوق", reqd: 1, default: "Restricted",
					options: [{ label: "مقيّد (لمشروع محدد)", value: "Restricted" }, { label: "عام (غير مقيّد)", value: "Unrestricted" }] },
				{ fieldname: "target_amount", fieldtype: "Currency", label: "المستهدف (ر.س)", options: "SAR" },
				{ fieldtype: "Section Break" },
				{ fieldname: "expected_start_date", fieldtype: "Date", label: "تاريخ البدء" },
				{ fieldtype: "Column Break" },
				{ fieldname: "expected_end_date", fieldtype: "Date", label: "تاريخ الانتهاء" },
				{ fieldtype: "Section Break", label: "صفحة التبرع" },
				{ fieldname: "is_public", fieldtype: "Check", label: "يظهر في موقع التبرع", default: 1 },
				{ fieldname: "public_title", fieldtype: "Data", label: "العنوان للمتبرعين" },
				{ fieldname: "public_description", fieldtype: "Small Text", label: "وصف قصير" },
				{ fieldtype: "Column Break" },
				{ fieldname: "public_image", fieldtype: "Attach Image", label: "صورة المشروع" },
				{ fieldname: "allow_custom_amount", fieldtype: "Check", label: "السماح بمبلغ يحدده المتبرع", default: 1 },
				{ fieldtype: "Section Break", label: "خيارات التبرع والأثر", collapsible: 0 },
				{ fieldname: "options", fieldtype: "Table", label: "مبالغ جاهزة", cannot_add_rows: false, in_place_edit: true, data: [],
					fields: [
						{ fieldname: "label", fieldtype: "Data", label: "الوصف", in_list_view: 1, reqd: 1, columns: 6 },
						{ fieldname: "amount", fieldtype: "Currency", label: "المبلغ", in_list_view: 1, reqd: 1, columns: 4 },
					] },
				{ fieldname: "impact_unit_label", fieldtype: "Data", label: "وحدة الأثر", description: "مثل: وجبة، عبوة ماء" },
				{ fieldname: "impact_units_per_sar", fieldtype: "Float", label: "وحدات لكل ريال" },
			],
			primary_action_label: "إنشاء المشروع",
			primary_action: (v) => {
				frappe
					.call({ method: "ataa_hub.staff_dashboard.create_project", args: { data: v }, freeze: true })
					.then(({ message }) => {
						d.hide();
						frappe.show_alert({ message: `أُنشئ المشروع ${message}`, indicator: "green" });
										this.load();
					});
			},
		});
		d.fields_dict.project_name.$input.on("change", () => {
			if (!d.get_value("public_title")) d.set_value("public_title", d.get_value("project_name"));
		});
		d.$wrapper.addClass("ataa-dialog");
		d.show();
	}

	newRequest(project) {
		const d = new frappe.ui.Dialog({
			title: "طلب صرف",
			fields: [
				{ fieldname: "project", fieldtype: "Select", label: "المشروع", reqd: 1, options: this.projectOptions(), default: project },
				{ fieldname: "balance", fieldtype: "HTML" },
				{ fieldname: "amount", fieldtype: "Currency", label: "المبلغ (ر.س)", options: "SAR", reqd: 1 },
				{ fieldname: "purpose", fieldtype: "Small Text", label: "الغرض", reqd: 1 },
				{ fieldname: "supplier", fieldtype: "Link", label: "المورد (اختياري)", options: "Supplier" },
				{ fieldname: "attachment", fieldtype: "Attach", label: "عرض سعر أو فاتورة (اختياري)" },
			],
			primary_action_label: "إرسال للمحاسب",
			primary_action: (v) =>
				frappe
					.call({ method: "ataa_hub.staff_dashboard.create_disbursement_request", args: v, freeze: true })
					.then(({ message }) => {
						d.hide();
						this.done(`أُرسل الطلب ${message} للمحاسب`);
					}),
		});
		this.showAvailable(d);
		d.$wrapper.addClass("ataa-dialog");
		d.show();
	}

	newCustody(project) {
		const d = new frappe.ui.Dialog({
			title: "طلب عهدة",
			fields: [
				{ fieldname: "intro", fieldtype: "HTML", options: '<p class="text-muted">مبلغ نقدي يُصرف لك لمشتريات المشروع، تسجّل فيه كل شراء مع فاتورته، ويُقفل عند انتهائه.</p>' },
				{ fieldname: "project", fieldtype: "Select", label: "المشروع", reqd: 1, options: this.projectOptions(), default: project },
				{ fieldname: "balance", fieldtype: "HTML" },
				{ fieldname: "amount", fieldtype: "Currency", label: "مبلغ العهدة (ر.س)", options: "SAR", reqd: 1 },
				{ fieldname: "purpose", fieldtype: "Small Text", label: "الغرض", reqd: 1 },
			],
			primary_action_label: "إرسال الطلب",
			primary_action: (v) =>
				frappe
					.call({ method: "ataa_hub.staff_dashboard.create_custody", args: { project: v.project, amount: v.amount, purpose: v.purpose }, freeze: true })
					.then(({ message }) => {
						d.hide();
						this.done(`أُرسل طلب العهدة ${message} للمحاسب`);
					}),
		});
		this.showAvailable(d);
		d.$wrapper.addClass("ataa-dialog");
		d.show();
	}

	showAvailable(d) {
		const show = () => {
			const p = this.d.projects.find((x) => x.name === d.get_value("project"));
			d.fields_dict.balance.$wrapper.html(
				p ? `<div class="ataa-available">المتاح للصرف في <b>${this.esc(p.title)}</b>: <b>${this.money(p.available, 2)}</b></div>` : ""
			);
		};
		d.fields_dict.project.$input.on("change", show);
		setTimeout(show, 50);
	}
}
