"""QR code generation & validation (PRD 6 - QR Code System, 10 - Security).

QR images are rendered on the fly (never written to disk) and their payload
is a signed token so a scanner can trust it wasn't forged offline (PRD 10:
"Signed QR token").
"""

import base64
from io import BytesIO

import qrcode
from django.core import signing
from django.urls import reverse

SIGNING_SALT = "siwak.qr"


def sign_payload(kind: str, token: str) -> str:
    """Wrap a raw DB token in a signed string. `kind` is 'registrasi' or 'kupon'."""
    return signing.dumps({"kind": kind, "token": token}, salt=SIGNING_SALT)


def unsign_payload(signed_value: str, max_age_seconds: int = 60 * 60 * 24 * 30):
    """Return {'kind': ..., 'token': ...} or raise signing.BadSignature/SignatureExpired."""
    return signing.loads(signed_value, salt=SIGNING_SALT, max_age=max_age_seconds)


def qr_png_data_uri(data: str) -> str:
    """Render `data` as a QR code and return a base64 data: URI (no file I/O)."""
    img = qrcode.make(data, box_size=8, border=2)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _qr_verify_data_uri(request, kind: str, token: str) -> str:
    """QR berisi URL absolut `qr_verify` untuk token ini, supaya kamera HP
    panitia langsung membuka halaman pindainya."""
    signed = sign_payload(kind, token)
    return qr_png_data_uri(request.build_absolute_uri(reverse("siwak:qr_verify", args=[signed])))


def registrasi_qr_data_uri(request, rsvp) -> str:
    return _qr_verify_data_uri(request, "registrasi", rsvp.qr_registrasi_token)


def kupon_qr_data_uri(request, rsvp) -> str:
    return _qr_verify_data_uri(request, "kupon", rsvp.qr_kupon_token)
