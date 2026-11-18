// Membership sign-up: pick a tier card, the server checks the request and returns Moyasar's
// form settings. The first year is paid with "save card" on; the callback page verifies it
// with the secret key, and ERPNext's Subscription bills the next years.
(function () {
	const form = document.getElementById("membership-form");
	if (!form) return;
	const dialog = document.getElementById("join");
	const $ = (id) => document.getElementById(id);
	const value = (id) => ($(id) ? $(id).value.trim() : undefined);
	const errorBox = $("form-error");
	const tiers = window.ATAA.tiers || {};

	function showError(message) {
		errorBox.textContent = message;
		errorBox.hidden = !message;
	}

	function syncSummary() {
		const t = form.querySelector('input[name="tier"]:checked');
		const info = t && tiers[t.value];
		$("tier-summary").textContent = info ? `عضوية ${info.label} — ${info.price} ر.س سنوياً، تتجدد تلقائياً كل عام.` : "";
	}
	form.addEventListener("change", syncSummary);

	document.addEventListener("click", (e) => {
		const join = e.target.closest("[data-join]");
		if (!join) return;
		const radio = form.querySelector(`input[name="tier"][value="${join.dataset.join}"]`);
		if (radio) radio.checked = true;
		syncSummary();
		showError("");
		dialog.showModal();
	});

	form.addEventListener("submit", async (e) => {
		e.preventDefault();
		showError("");
		const tier = form.querySelector('input[name="tier"]:checked');
		if (!tier) return showError("اختر مستوى العضوية.");
		let mobile;
		if ($("mobile")) {
			mobile = window.Ataa.saMobile(value("mobile"));
			if (!mobile) return showError("رقم الجوال بالصيغة 05XXXXXXXX.");
		}

		const button = $("continue-btn");
		button.disabled = true;
		try {
			const d = await window.Ataa.post("ataa_hub.portal.membership.start_signup", {
				tier: tier.value,
				full_name: value("full-name"),
				email: value("email"),
				mobile: mobile,
			});
			showPayment(d);
		} catch (err) {
			showError(err.message);
		} finally {
			button.disabled = false;
		}
	});

	function showPayment(d) {
		form.hidden = true;
		$("payment-step").hidden = false;
		$("payment-summary").textContent = `${d.description} — ${d.amount.toLocaleString("en-US")} ر.س`;
		Moyasar.init({
			element: ".mysr-form",
			amount: d.amount_halalas,
			currency: d.currency,
			description: d.description,
			publishable_api_key: d.publishable_key,
			callback_url: d.callback_url,
			methods: ["creditcard"],
			supported_networks: ["mada", "visa", "mastercard"],
			credit_card: { save_card: true },
			metadata: d.metadata,
			language: "ar",
		});
	}

	$("back-btn").addEventListener("click", () => window.location.reload());
	syncSummary();
})();
