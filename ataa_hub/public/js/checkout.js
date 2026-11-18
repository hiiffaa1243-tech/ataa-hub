// /donate/checkout: one payment for the whole cart.
// Card: the server creates one Draft donation per line and returns Moyasar's settings; the
// callback page asks Moyasar (with the secret key) whether it was paid before recording anything.
// Bank transfer: the donations are created as drafts with the receipt; the accountant submits them.
(function () {
	const { Cart, post, fmt, saMobile } = window.Ataa;
	const $ = (id) => document.getElementById(id);
	const esc = (s) => String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
	const err = $("pay-error");
	let lines = Cart.load();

	function showError(msg) {
		err.textContent = msg || "";
		err.hidden = !msg;
	}

	function draw() {
		lines = Cart.load();
		$("checkout").hidden = !lines.length;
		$("checkout-empty").hidden = !!lines.length || !$("bank-done").hidden;
		$("summary-lines").innerHTML = lines
			.map(
				(l) => `<div><dt>${esc(l.title)}${l.qty > 1 ? ` × ${l.qty}` : ""}${l.gift ? " · إهداء" : ""}</dt><dd>${fmt(l.unit * l.qty)} ر.س</dd></div>`
			)
			.join("");
		$("sum-total").textContent = fmt(Cart.total(lines));
	}

	function donor() {
		const mobile = saMobile($("donor-mobile").value);
		if (mobile === null) throw new Error("رقم الجوال بالصيغة 05XXXXXXXX.");
		return { donor_name: $("donor-name").value.trim(), mobile: mobile || undefined };
	}

	// accordion
	document.querySelectorAll(".ataa-acc__head").forEach((head) =>
		head.addEventListener("click", () => {
			document.querySelectorAll(".ataa-acc").forEach((acc) => {
				const open = acc === head.parentElement;
				acc.classList.toggle("is-open", open);
				acc.querySelector(".ataa-acc__head").setAttribute("aria-expanded", open);
			});
			showError("");
		})
	);

	// ---------------------------------------------------------------- card
	const cardBtn = $("card-btn");
	if (cardBtn)
		cardBtn.addEventListener("click", async () => {
			showError("");
			cardBtn.disabled = true;
			cardBtn.textContent = "جاري التجهيز…";
			try {
				const d = await post("ataa_hub.payments.create_pending_cart", { items: Cart.payload(), ...donor() });
				$("card-start").hidden = true;
				$("card-form").hidden = false;
				Moyasar.init({
					element: ".mysr-form",
					amount: d.amount_halalas, // halalas
					currency: d.currency,
					description: d.description,
					publishable_api_key: d.publishable_key,
					callback_url: d.callback_url,
					methods: ["creditcard"],
					supported_networks: ["mada", "visa", "mastercard"],
					metadata: d.metadata,
					language: "ar",
				});
			} catch (e) {
				showError(e.message);
			} finally {
				cardBtn.disabled = false;
				cardBtn.textContent = "متابعة للدفع بالبطاقة";
			}
		});

	// ---------------------------------------------------------------- bank transfer
	document.addEventListener("click", async (e) => {
		const b = e.target.closest("[data-copy]");
		if (!b) return;
		e.preventDefault();
		try {
			await navigator.clipboard.writeText(b.dataset.copy);
			window.Ataa.toast("نُسخ رقم الآيبان");
		} catch (ex) {
			/* clipboard blocked */
		}
	});

	const proof = $("proof");
	if (proof)
		proof.addEventListener("change", () => {
			const f = proof.files[0];
			$("proof-label").textContent = f ? f.name : "ارفع إيصال التحويل";
		});

	const readFile = (file) =>
		new Promise((resolve, reject) => {
			const r = new FileReader();
			r.onload = () => resolve(r.result);
			r.onerror = () => reject(new Error("تعذرت قراءة الملف."));
			r.readAsDataURL(file);
		});

	const bankBtn = $("bank-btn");
	if (bankBtn)
		bankBtn.addEventListener("click", async () => {
			showError("");
			const file = proof.files[0];
			const bank = document.querySelector('input[name="bank"]:checked');
			if (!bank) return showError("اختر الحساب الذي حوّلت إليه.");
			if (!file) return showError("أرفق إيصال التحويل.");
			if (file.size > 5 * 1024 * 1024) return showError("حجم الإيصال يجب ألا يتجاوز 5 ميجابايت.");
			bankBtn.disabled = true;
			bankBtn.textContent = "جاري الإرسال…";
			try {
				const d = await post("ataa_hub.payments.submit_bank_transfer", {
					items: Cart.payload(),
					bank_account: bank.value,
					file_name: file.name,
					file_data: await readFile(file),
					...donor(),
				});
				$("bank-done").hidden = false;
				Cart.clear();
				$("bank-refs").innerHTML = d.donation_ids
					.map((id) => `<li><span>رقم التبرع</span><strong dir="ltr">${esc(id)}</strong></li>`)
					.join("");
			} catch (e) {
				showError(e.message);
			} finally {
				bankBtn.disabled = false;
				bankBtn.textContent = "قم بالتحويل";
			}
		});

	document.addEventListener("ataa:cart", draw);
	draw();
})();
