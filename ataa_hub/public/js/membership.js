// Membership sign-up: the server checks the request and returns Moyasar's form settings.
// The first month is paid with "save card" on; the callback page verifies it with the secret key.
(function () {
	const form = document.getElementById("membership-form");
	if (!form) return;
	const $ = (id) => document.getElementById(id);
	const value = (id) => ($(id) ? $(id).value.trim() : undefined);
	const errorBox = $("form-error");

	function showError(message) {
		errorBox.textContent = message;
		errorBox.hidden = !message;
	}

	function serverMessage(body) {
		try {
			const messages = JSON.parse(body._server_messages || "[]");
			if (messages.length) return JSON.parse(messages[0]).message.replace(/<[^>]+>/g, "");
		} catch (e) {
			/* fall through */
		}
		return body.exception || "تعذر إكمال الطلب، حاول مرة أخرى.";
	}

	form.addEventListener("submit", async (e) => {
		e.preventDefault();
		showError("");
		const tier = form.querySelector('input[name="tier"]:checked');
		const mobile = (value("mobile") || "").replace(/\s/g, "");
		if (!tier) return showError("اختر مستوى العضوية.");
		if ($("mobile") && !/^\+9665\d{8}$/.test(mobile)) return showError("رقم الجوال بالصيغة +9665XXXXXXXX.");

		const button = $("continue-btn");
		button.disabled = true;
		try {
			const res = await fetch("/api/method/ataa_hub.portal.membership.start_signup", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Accept: "application/json",
					"X-Frappe-CSRF-Token": window.ATAA.csrf_token,
				},
				body: JSON.stringify({
					tier: tier.value,
					full_name: value("full-name"),
					email: value("email"),
					mobile: mobile || undefined,
				}),
			});
			const body = await res.json();
			if (!res.ok) throw new Error(serverMessage(body));
			showPayment(body.message);
		} catch (err) {
			showError(err.message);
		} finally {
			button.disabled = false;
		}
	});

	function showPayment(d) {
		form.hidden = true;
		$("payment-step").hidden = false;
		$("payment-summary").textContent = `${d.description} — ${d.amount.toLocaleString("ar-SA")} ر.س`;
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
})();
