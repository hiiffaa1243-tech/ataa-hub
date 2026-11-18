// Staff open the desk on their dashboard, never on the apps screen (see ataa_hub/boot.py).
function ataa_staff_home() {
	if (!frappe.boot || !frappe.boot.ataa_staff) return;
	const route = frappe.get_route ? frappe.get_route() : [];
	if (!route.length || (route.length === 1 && !route[0])) {
		frappe.set_route("ataa-home");
	}
}

$(document).on("page-change", ataa_staff_home);
frappe.router && frappe.router.on && frappe.router.on("change", ataa_staff_home);
