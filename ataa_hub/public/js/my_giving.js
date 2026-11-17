// Donor portal actions. The server always takes the donor from the session, never from here.
(function () {
	const $ = (id) => document.getElementById(id);

	function serverMessage(body) {
		try {
			const messages = JSON.parse(body._server_messages || "[]");
			if (messages.length) return JSON.parse(messages[0]).message.replace(/<[^>]+>/g, "");
		} catch (e) {
			/* fall through */
		}
		return body.exception || "تعذر إكمال الطلب، حاول مرة أخرى.";
	}

	async function call(method, args) {
		const res = await fetch(`/api/method/${method}`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
				"X-Frappe-CSRF-Token": window.ATAA.csrf_token,
			},
			body: JSON.stringify(args || {}),
		});
		const body = await res.json();
		if (!res.ok) throw new Error(serverMessage(body));
		return body.message;
	}

	function showError(box, message) {
		if (!box) return alert(message);
		box.textContent = message;
		box.hidden = !message;
	}

	// ------------------------------------------------ membership card actions
	document.addEventListener("click", async (e) => {
		const button = e.target.closest("[data-action]");
		if (!button) return;
		e.preventDefault();
		const box = $("action-error");
		try {
			if (button.dataset.action === "change-tier") {
				const tier = $("new-tier").value;
				if (!confirm("تغيير المستوى يبدأ من الشهر القادم. متابعة؟")) return;
				await call("ataa_hub.portal.membership.change_tier", { tier });
			} else if (button.dataset.action === "cancel") {
				if (!confirm("إيقاف الاشتراك؟ تبقى عضويتك حتى نهاية الشهر المدفوع.")) return;
				await call("ataa_hub.portal.membership.cancel_membership");
			}
			window.location.reload();
		} catch (err) {
			showError(box, err.message);
		}
	});

	// ------------------------------------------------ update card (Moyasar save-only token)
	// Card details go straight from the browser to Moyasar with the publishable key;
	// our server only ever receives the token id on the callback page.
	const cardForm = $("card-form");
	if (cardForm) {
		cardForm.addEventListener("submit", async (e) => {
			e.preventDefault();
			const box = $("card-error");
			showError(box, "");
			const button = $("card-btn");
			button.disabled = true;
			try {
				const res = await fetch("https://api.moyasar.com/v1/tokens", {
					method: "POST",
					headers: { "Content-Type": "application/json", Accept: "application/json" },
					body: JSON.stringify({
						publishable_api_key: cardForm.dataset.key,
						save_only: true,
						name: $("card-name").value.trim(),
						number: $("card-number").value.replace(/\s/g, ""),
						month: $("card-month").value.trim(),
						year: $("card-year").value.trim(),
						cvc: $("card-cvc").value.trim(),
						callback_url: cardForm.dataset.callback,
					}),
				});
				const token = await res.json();
				if (!res.ok) throw new Error(token.message || "رفض ميسّر البطاقة.");
				window.location.href =
					token.verification_url || `${cardForm.dataset.callback}?id=${encodeURIComponent(token.id)}`;
			} catch (err) {
				showError(box, err.message);
				button.disabled = false;
			}
		});
	}
})();
