// M0 spike: connect to Frappe's socket.io server as a guest (no cookie) and report
// which publish_realtime events arrive. Run from apps/frappe so socket.io-client resolves.
//   node guest_socket.js <site>
const { io } = require("socket.io-client");

const site = process.argv[2];
const received = new Set();
const socket = io(`http://localhost:9000/${site}`, {
	transports: ["websocket"],
	extraHeaders: { Origin: "http://localhost:8000" },
	reconnection: false,
});

socket.on("connect", () => console.log(`SPIKE: guest socket connected (id ${socket.id})`));
socket.on("connect_error", (e) => {
	console.log(`SPIKE: guest socket connect_error: ${e.message}`);
	process.exit(1);
});
socket.onAny((event) => {
	if (event.startsWith("ataa_spike")) received.add(event);
});

setTimeout(() => {
	console.log(`SPIKE: guest received: ${[...received].join(", ") || "nothing"}`);
	socket.close();
	process.exit(received.size ? 0 : 1);
}, 25000);
