from frappe import _


def get_data():
	"""Links shown at the bottom of the project form: its donations and disbursement requests."""
	return {
		"fieldname": "project",
		"transactions": [
			{"label": _("التبرعات والصرف"), "items": ["Donation", "Disbursement Request"]},
		],
	}
