// Public site helpers: the cart (kept in the browser), buy boxes, quick-donate and gift dialogs.
// The cart only holds choices. Amounts are re-checked on the server against the live project
// when the donor pays (payments.cart_lines), so editing localStorage changes nothing.
(function () {
	const KEY = "ataa_cart_v1";
	const MAX_LINES = 20;
	const MAX_QTY = 100;
	const fmt = (n) => Number(n || 0).toLocaleString("en-US", { maximumFractionDigits: 2 });
	const $$ = (root, sel) => Array.from(root.querySelectorAll(sel));

	// ------------------------------------------------------------------ cart store
	const Cart = {
		load() {
			try {
				const lines = JSON.parse(localStorage.getItem(KEY) || "[]");
				return Array.isArray(lines) ? lines : [];
			} catch (e) {
				return [];
			}
		},
		save(lines) {
			try {
				localStorage.setItem(KEY, JSON.stringify(lines));
			} catch (e) {
				/* private mode: cart lives for this page only */
			}
			render();
		},
		add(line) {
			const lines = Cart.load();
			const same = !line.gift && lines.find((l) => !l.gift && l.code === line.code && l.unit === line.unit);
			if (same) same.qty = Math.min(MAX_QTY, same.qty + line.qty);
			else {
				if (lines.length >= MAX_LINES) throw new Error(`الحد الأقصى ${MAX_LINES} تبرعاً في السلة.`);
				lines.push({ ...line, id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6) });
			}
			Cart.save(lines);
		},
		setQty(id, qty) {
			const lines = Cart.load();
			const l = lines.find((x) => x.id === id);
			if (l) l.qty = Math.max(1, Math.min(MAX_QTY, qty));
			Cart.save(lines);
		},
		remove(id) {
			Cart.save(Cart.load().filter((l) => l.id !== id));
		},
		clear() {
			Cart.save([]);
		},
		total(lines = Cart.load()) {
			return lines.reduce((s, l) => s + l.unit * l.qty, 0);
		},
		payload(lines = Cart.load()) {
			return lines.map((l) => ({ project_code: l.code, amount: l.unit, qty: l.qty, gift: l.gift || null }));
		},
	};

	function render(bump = true) {
		const lines = Cart.load();
		const count = lines.length;
		$$(document, '[data-ataa="cart-count"]').forEach((b) => {
			b.textContent = count;
			b.hidden = !count;
		});
		const pill = document.querySelector('[data-ataa="cart-pill"]');
		if (pill) {
			pill.hidden = !count;
			pill.querySelector('[data-ataa="pill-count"]').textContent = count;
			pill.querySelector('[data-ataa="pill-total"]').textContent = fmt(Cart.total(lines));
			if (bump) {
				pill.classList.remove("is-bump");
				void pill.offsetWidth;
				pill.classList.add("is-bump");
			}
		}
		document.dispatchEvent(new CustomEvent("ataa:cart"));
	}

	function toast(text) {
		const t = document.createElement("div");
		t.className = "ataa-toast";
		t.setAttribute("role", "status");
		t.textContent = text;
		document.body.appendChild(t);
		setTimeout(() => t.remove(), 2200);
	}

	function serverMessage(body) {
		try {
			const messages = JSON.parse(body._server_messages || "[]");
			if (messages.length) return JSON.parse(messages[0]).message.replace(/<[^>]+>/g, "");
		} catch (e) {
			/* fall through */
		}
		return body.exception ? String(body.exception).split(":").pop().trim() : "تعذر إكمال الطلب، حاول مرة أخرى.";
	}

	async function post(method, data) {
		const res = await fetch(`/api/method/${method}`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
				"X-Frappe-CSRF-Token": window.ATAA.csrf_token,
			},
			body: JSON.stringify(data),
		});
		const body = await res.json().catch(() => ({}));
		if (!res.ok) throw new Error(serverMessage(body));
		return body.message;
	}

	let catalogPromise;
	function catalog() {
		catalogPromise =
			catalogPromise ||
			fetch("/api/method/ataa_hub.projects.catalog", { headers: { Accept: "application/json" } })
				.then((r) => r.json())
				.then((b) => b.message || []);
		return catalogPromise;
	}

	// Saudi mobile: accept 05XXXXXXXX / 9665… / +9665… and send +9665XXXXXXXX.
	function saMobile(raw) {
		let m = String(raw || "").replace(/[\s-]/g, "");
		if (!m) return "";
		if (/^05\d{8}$/.test(m)) m = "+966" + m.slice(1);
		else if (/^9665\d{8}$/.test(m)) m = "+" + m;
		else if (/^5\d{8}$/.test(m)) m = "+966" + m;
		return /^\+9665\d{8}$/.test(m) ? m : null;
	}

	// ------------------------------------------------------------------ amount pickers
	// One helper for the buy boxes and the quick dialog: chips + optional custom amount.
	function picker(root, { chips, custom, total, qty }) {
		const state = { unit: 0, label: "" };
		const customInput = custom && custom.querySelector("input");
		function sync() {
			const chosen = chips().find((c) => c.classList.contains("is-selected"));
			if (!chosen) state.unit = 0;
			else if (chosen.dataset.amount === "custom") {
				state.unit = Math.round(Number(customInput && customInput.value) * 100) / 100 || 0;
				state.label = "";
			} else {
				state.unit = Number(chosen.dataset.amount);
				state.label = chosen.dataset.label || "";
			}
			if (custom) custom.hidden = !(chosen && chosen.dataset.amount === "custom");
			if (total) total.textContent = fmt(state.unit * (qty ? qty() : 1));
		}
		root.addEventListener("click", (e) => {
			const chip = e.target.closest(".ataa-chip");
			if (!chip || !root.contains(chip)) return;
			chips().forEach((c) => {
				c.classList.toggle("is-selected", c === chip);
				c.setAttribute("aria-checked", c === chip);
			});
			sync();
			if (chip.dataset.amount === "custom" && customInput) customInput.focus();
		});
		if (customInput) customInput.addEventListener("input", sync);
		sync();
		return { state, sync };
	}

	function validUnit(unit) {
		if (!unit || unit < 1) return "اختر خيار التبرع أو اكتب مبلغاً صحيحاً.";
		if (unit > 100000) return "الحد الأعلى للتبرع 100,000 ريال.";
		return "";
	}

	// ------------------------------------------------------------------ buy boxes
	function initBuyBox(box) {
		const project = JSON.parse(box.dataset.ataaBuy);
		const out = box.querySelector(".ataa-stepper output");
		const err = box.querySelector("[data-error]");
		let qty = 1;
		const p = picker(box, {
			chips: () => $$(box, ".ataa-chip"),
			custom: box.querySelector(".ataa-custom"),
			total: box.querySelector("[data-total]"),
			qty: () => qty,
		});
		box.querySelector(".ataa-stepper").addEventListener("click", (e) => {
			const b = e.target.closest("[data-step]");
			if (!b) return;
			qty = Math.max(1, Math.min(MAX_QTY, qty + Number(b.dataset.step)));
			out.textContent = qty;
			p.sync();
		});
		const line = () => ({
			code: project.code,
			title: project.title,
			image: project.image,
			unit: p.state.unit,
			label: p.state.label,
			qty,
		});
		function check() {
			const msg = validUnit(p.state.unit);
			err.textContent = msg;
			err.hidden = !msg;
			return !msg;
		}
		box.addEventListener("click", (e) => {
			const act = e.target.closest("[data-act]");
			if (!act || !check()) return;
			try {
				if (act.dataset.act === "gift") return Gift.open(line());
				Cart.add(line());
				if (act.dataset.act === "now") window.location.href = "/donate/checkout";
				else toast("أُضيف التبرع إلى السلة");
			} catch (ex) {
				err.textContent = ex.message;
				err.hidden = false;
			}
		});
	}

	// ------------------------------------------------------------------ quick dialog
	const Quick = {
		async open(code) {
			const dlg = document.getElementById("ataa-quick");
			if (!dlg) return;
			dlg.showModal();
			const select = dlg.querySelector('[data-q="project"]');
			const projects = await catalog();
			if (!Quick.ready) {
				select.innerHTML = projects
					.map((p) => `<option value="${p.code}">${p.title.replace(/</g, "&lt;")}</option>`)
					.join("");
				select.addEventListener("change", () => Quick.fill(projects));
				Quick.picker = picker(dlg.querySelector(".ataa-modal__body"), {
					chips: () => $$(dlg, '[data-q="chips"] .ataa-chip'),
					custom: dlg.querySelector('[data-q="custom"]'),
					total: dlg.querySelector('[data-q="total"]'),
				});
				dlg.querySelector('[data-q="now"]').addEventListener("click", () => Quick.submit(projects, true));
				dlg.querySelector('[data-q="add"]').addEventListener("click", () => Quick.submit(projects, false));
				Quick.ready = true;
			}
			if (code && projects.some((p) => p.code === code)) select.value = code;
			Quick.fill(projects);
		},
		fill(projects) {
			const dlg = document.getElementById("ataa-quick");
			const p = projects.find((x) => x.code === dlg.querySelector('[data-q="project"]').value) || projects[0];
			if (!p) return;
			const chips = p.options.map(
				(o, i) =>
					`<button type="button" class="ataa-chip${i === 0 ? " is-selected" : ""}" data-amount="${o.amount}" data-label="${o.label.replace(/"/g, "&quot;")}">${o.label.replace(/</g, "&lt;")} <small>${fmt(o.amount)} ر.س</small></button>`
			);
			if (p.allow_custom_amount)
				chips.push(
					`<button type="button" class="ataa-chip${p.options.length ? "" : " is-selected"}" data-amount="custom">مبلغ آخر</button>`
				);
			dlg.querySelector('[data-q="chips"]').innerHTML = chips.join("");
			Quick.picker.sync();
		},
		submit(projects, now) {
			const dlg = document.getElementById("ataa-quick");
			const err = dlg.querySelector('[data-q="error"]');
			const p = projects.find((x) => x.code === dlg.querySelector('[data-q="project"]').value);
			const msg = !p ? "اختر نوع التبرع." : validUnit(Quick.picker.state.unit);
			err.textContent = msg;
			err.hidden = !msg;
			if (msg) return;
			try {
				Cart.add({ code: p.code, title: p.title, image: p.image, unit: Quick.picker.state.unit, label: Quick.picker.state.label, qty: 1 });
			} catch (ex) {
				err.textContent = ex.message;
				err.hidden = false;
				return;
			}
			if (now) window.location.href = "/donate/checkout";
			else {
				dlg.close();
				toast("أُضيف التبرع إلى السلة");
			}
		},
	};

	// ------------------------------------------------------------------ gift dialog
	const Gift = {
		line: null,
		open(line) {
			const dlg = document.getElementById("ataa-gift");
			Gift.line = line;
			const f = (k) => dlg.querySelector(`[data-g="${k}"]`);
			f("summary").textContent = `${line.title} — ${fmt(line.unit * line.qty)} ر.س. يصل المهدى إليه رابط بطاقة الإهداء بعد اكتمال الدفع.`;
			f("error").hidden = true;
			if (!Gift.ready) {
				f("now").addEventListener("click", () => Gift.submit(true));
				f("add").addEventListener("click", () => Gift.submit(false));
				Gift.ready = true;
			}
			dlg.showModal();
			f("recipient_name").focus();
		},
		submit(now) {
			const dlg = document.getElementById("ataa-gift");
			const f = (k) => dlg.querySelector(`[data-g="${k}"]`);
			const val = (k) => f(k).value.trim();
			const mobile = saMobile(val("recipient_mobile"));
			const email = val("recipient_email");
			let msg = "";
			if (!val("recipient_name")) msg = "اكتب اسم المهدى إليه.";
			else if (mobile === null) msg = "جوال المهدى إليه بالصيغة 05XXXXXXXX.";
			else if (!mobile && !email) msg = "أدخل جوال المهدى إليه أو بريده.";
			else if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) msg = "البريد الإلكتروني غير صحيح.";
			f("error").textContent = msg;
			f("error").hidden = !msg;
			if (msg) return;
			const gift = {
				recipient_name: val("recipient_name"),
				recipient_mobile: mobile,
				recipient_email: email,
				sender_name: val("sender_name"),
				occasion: f("occasion").value,
				message: val("message"),
				show_amount: f("show_amount").checked ? 1 : 0,
			};
			try {
				Cart.add({ ...Gift.line, gift });
			} catch (ex) {
				f("error").textContent = ex.message;
				f("error").hidden = false;
				return;
			}
			f("form").reset();
			dlg.close();
			if (now) window.location.href = "/donate/checkout";
			else toast("أُضيف الإهداء إلى السلة");
		},
	};

	// ------------------------------------------------------------------ boot
	document.addEventListener("click", (e) => {
		const q = e.target.closest('[data-ataa="quick"]');
		if (q) Quick.open(q.dataset.code);
		if (e.target.closest('[data-ataa="menu"]')) document.getElementById("ataa-nav").classList.toggle("is-open");
		// click on the dimmed backdrop closes a dialog
		if (e.target.classList && e.target.classList.contains("ataa-modal")) e.target.close();
	});
	const here = window.location.pathname;
	$$(document, ".ataa-nav a").forEach((a) => {
		const path = a.getAttribute("href");
		if (here === path || here.startsWith(path + "/")) a.classList.add("is-active");
	});
	$$(document, "[data-ataa-buy]").forEach(initBuyBox);
	window.addEventListener("storage", (e) => e.key === KEY && render(false));
	render(false);

	window.Ataa = { Cart, catalog, post, toast, fmt, saMobile, Quick, Gift };
})();
