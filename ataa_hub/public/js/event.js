// Booth live screen: polls the cached feed every 5 s (guests cannot use socket.io on v16).
// The feed has no donor data. Text is set with textContent, never as HTML.
(function () {
	const root = document.querySelector(".ev");
	if (!root) return;
	const $ = (id) => document.getElementById(id);
	const code = root.dataset.code;
	const POLL_MS = 5000;
	const fmt = (n) => Math.round(n).toLocaleString("ar-SA");
	let lastCount = null;

	function li(className, parts) {
		const el = document.createElement("li");
		if (className) el.className = className;
		for (const [cls, text] of parts) {
			const span = document.createElement("span");
			span.className = cls;
			span.textContent = text;
			el.appendChild(span);
		}
		return el;
	}

	function render(feed) {
		$("ev-total").textContent = fmt(feed.total);
		$("ev-target").textContent = fmt(feed.target);
		$("ev-count").textContent = fmt(feed.count);
		$("ev-hour").textContent = fmt(feed.last_hour);
		$("ev-fill").style.width = `${feed.progress || 0}%`;
		$("ev-pct").textContent = `${feed.progress || 0}%`;
		$("ev-updated").textContent = feed.updated_at;

		const fresh = lastCount !== null && feed.count > lastCount;
		$("ev-latest").replaceChildren(
			...feed.latest.map((d, i) =>
				li(fresh && i === 0 ? "is-new" : "", [
					["ev__amt", `${fmt(d.amount)} ر.س`],
					["ev__prj", d.project_title],
					["ev__trm", `${d.terminal}${d.time ? " · " + d.time : ""}`],
				])
			)
		);
		$("ev-projects").replaceChildren(
			...feed.by_project.map((p) => li("", [["ev__prj", p.project_title], ["ev__amt", fmt(p.amount)]]))
		);
		$("ev-terminals").replaceChildren(
			...feed.by_terminal.map((t) => li("", [["ev__prj", t.terminal], ["ev__amt", fmt(t.amount)]]))
		);
		lastCount = feed.count;
	}

	async function poll() {
		try {
			const res = await fetch(
				`/api/method/ataa_hub.public.event_feed?event_code=${encodeURIComponent(code)}`,
				{ headers: { Accept: "application/json" }, cache: "no-store" }
			);
			if (!res.ok) throw new Error(res.status);
			render((await res.json()).message);
			$("ev-dot").classList.remove("is-off");
		} catch (e) {
			$("ev-dot").classList.add("is-off"); // keep showing the last data
		} finally {
			setTimeout(poll, POLL_MS);
		}
	}

	render(window.ATAA_EVENT_FEED);
	setTimeout(poll, POLL_MS);
})();
