"""Small helpers shared by print formats and portal pages."""

import base64
import io

import pyqrcode


def qr_data_uri(text: str | None, scale: int = 4) -> str:
	"""PNG QR code as a data: URI, usable in Jinja print formats and PDFs (wkhtmltopdf)."""
	if not text:
		return ""
	buffer = io.BytesIO()
	pyqrcode.create(text, error="M").png(buffer, scale=scale, quiet_zone=2)
	return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
