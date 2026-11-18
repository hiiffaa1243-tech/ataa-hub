// /donate/cart: lines, quantities, total, and the "complete your reward" suggestions.
(function () {
	const { Cart, catalog, fmt } = window.Ataa;
	const $ = (id) => document.getElementById(id);
	const esc = (s) => String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

	function draw() {
		const lines = Cart.load();
		$("cart").hidden = !lines.length;
		$("cart-empty").hidden = !!lines.length;
		$("cart-lines").innerHTML = lines
			.map(
				(l) => `
			<div class="ataa-cart-line" data-id="${esc(l.id)}">
				${l.image ? `<img src="${esc(l.image)}" alt="">` : '<div class="ataa-thumb"></div>'}
				<div>
					<h3>${esc(l.title)}</h3>
					<p>${l.label ? esc(l.label) + " · " : ""}${fmt(l.unit)} ر.س</p>
					${l.gift ? `<span class="ataa-tag">إهداء إلى ${esc(l.gift.recipient_name)}</span>` : ""}
				</div>
				<div class="ataa-stepper">
					<button type="button" data-step="1" aria-label="زيادة">+</button>
					<output>${l.qty}</output>
					<button type="button" data-step="-1" aria-label="إنقاص">−</button>
				</div>
				<div class="ataa-line-total">${fmt(l.unit * l.qty)} <span class="ataa-sar">ر.س</span></div>
				<button type="button" class="ataa-remove" data-remove aria-label="حذف">
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>
				</button>
			</div>`
			)
			.join("");
		$("sum-count").textContent = lines.length;
		$("sum-gifts").textContent = lines.filter((l) => l.gift).length;
		$("sum-total").textContent = fmt(Cart.total(lines));
		upsell(lines);
	}

	async function upsell(lines) {
		const inCart = new Set(lines.map((l) => l.code));
		const projects = (await catalog()).filter((p) => !inCart.has(p.code) && p.options.length).slice(0, 4);
		$("upsell").hidden = !projects.length;
		$("upsell-grid").innerHTML = projects
			.map((p) => {
				const o = p.options[0];
				return `<div class="ataa-mini">
					${p.image ? `<img src="${esc(p.image)}" alt="">` : ""}
					<div><strong>${esc(p.title)}</strong><span>${esc(o.label)} · ${fmt(o.amount)} ر.س</span></div>
					<button type="button" class="ataa-btn ataa-btn--outline ataa-btn--sm" data-add="${esc(p.code)}">أضف</button>
				</div>`;
			})
			.join("");
		$("upsell-grid").onclick = (e) => {
			const b = e.target.closest("[data-add]");
			if (!b) return;
			const p = projects.find((x) => x.code === b.dataset.add);
			Cart.add({ code: p.code, title: p.title, image: p.image, unit: p.options[0].amount, label: p.options[0].label, qty: 1 });
		};
	}

	$("cart-lines").addEventListener("click", (e) => {
		const row = e.target.closest("[data-id]");
		if (!row) return;
		const id = row.dataset.id;
		const line = Cart.load().find((l) => l.id === id);
		if (!line) return;
		if (e.target.closest("[data-remove]")) Cart.remove(id);
		const step = e.target.closest("[data-step]");
		if (step) Cart.setQty(id, line.qty + Number(step.dataset.step));
	});
	$("clear-cart").addEventListener("click", () => Cart.clear());
	document.addEventListener("ataa:cart", draw);
	draw();
})();
