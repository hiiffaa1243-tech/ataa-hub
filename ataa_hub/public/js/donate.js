// Donation page: step 1 creates a Pending donation on the server,
// step 2 shows Moyasar's card form. The browser never decides whether a payment succeeded:
// the server re-checks the payment with Moyasar on the callback page and in the webhook.
(function () {
	const form = document.getElementById("donation-form");
	if (!form) return;

	const $ = (id) => document.getElementById(id);
	const errorBox = $("form-error");
	const customField = $("custom-amount-field");

	form.addEventListener("change", (e) => {
		if (e.target.name === "preset" && customField) {
			customField.hidden = e.target.value !== "custom";
		}
	});

	function selectedAmount() {
		const preset = form.querySelector('input[name="preset"]:checked');
		if (preset && preset.value !== "custom") return Number(preset.value);
		const custom = $("custom-amount");
		return custom ? Number(custom.value) : NaN;
	}

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

		const amount = selectedAmount();
		const mobile = $("donor-mobile").value.replace(/\s/g, "");
		if (!amount || amount < 1) return showError("اكتب مبلغاً صحيحاً.");
		if (mobile && !/^\+9665\d{8}$/.test(mobile)) return showError("رقم الجوال بالصيغة +9665XXXXXXXX.");

		const button = $("continue-btn");
		button.disabled = true;
		button.textContent = "جاري التجهيز…";

		try {
			const res = await fetch("/api/method/ataa_hub.payments.create_pending_donation", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Accept: "application/json",
					"X-Frappe-CSRF-Token": window.ATAA.csrf_token,
				},
				body: JSON.stringify({
					project_code: window.ATAA.project_code,
					amount: amount,
					donor_name: $("donor-name").value,
					mobile: mobile,
				}),
			});
			const body = await res.json();
			if (!res.ok) throw new Error(serverMessage(body));
			showPayment(body.message);
		} catch (err) {
			showError(err.message);
		} finally {
			button.disabled = false;
			button.textContent = "متابعة للدفع";
		}
	});

	function showPayment(d) {
		form.hidden = true;
		$("payment-step").hidden = false;
		$("payment-summary").textContent = `تبرع بمبلغ ${d.amount.toLocaleString("ar-SA")} ر.س — رقم التبرع ${d.donation_id}`;

		Moyasar.init({
			element: ".mysr-form",
			amount: d.amount_halalas, // Moyasar expects halalas
			currency: d.currency,
			description: d.description,
			publishable_api_key: d.publishable_key,
			callback_url: d.callback_url,
			methods: ["creditcard"],
			supported_networks: ["mada", "visa", "mastercard"],
			metadata: { donation_id: d.donation_id },
			language: "ar",
		});
	}

	$("back-btn").addEventListener("click", () => window.location.reload());
})();
