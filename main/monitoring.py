"""Pembantu monitoring Sentry: pembersih URL dan konteks user minimal.

Sengaja tidak mengimpor model apa pun, karena modul ini diimpor dari
settings.py (sebelum aplikasi Django siap).
"""

import re

import sentry_sdk

# EventScrubber Sentry hanya mengganti nilai berdasarkan NAMA KUNCI (header,
# cookie, data form, variabel lokal, ...). Ia tidak pernah menyentuh
# `request.url` dan `request.query_string`, padahal dua rahasia justru ada di
# sana:
#   * token QR bertanda tangan di jalur /siwak/qr/<signed>/ — berlaku 30 hari
#     dan cukup untuk meng-check-in peserta atau menukar kuponnya;
#   * tiket CAS di `?ticket=ST-...` saat SSO UI mengembalikan user ke situs.
# Permintaan keluar ke SSO UI tidak perlu diurus di sini: Sentry sendiri sudah
# menyaring query string URL keluar.
_JALUR_QR = re.compile(r"(/siwak/qr/)[^/?#]+")
_TIKET_CAS = re.compile(r"((?:^|[?&])ticket=)[^&#]*")
DISARING = "[Filtered]"


def _samarkan(teks):
    return _TIKET_CAS.sub(rf"\g<1>{DISARING}", _JALUR_QR.sub(rf"\g<1>{DISARING}", teks))


def bersihkan_event(event, hint):
    """`before_send` / `before_send_transaction`: samarkan rahasia di URL."""
    request = event.get("request")
    if isinstance(request, dict):
        for kunci in ("url", "query_string"):
            if isinstance(request.get(kunci), str):
                request[kunci] = _samarkan(request[kunci])
    return event


class SentryUserMiddleware:
    """Tempelkan HANYA `request.user.pk` ke event Sentry.

    Cukup untuk menghitung berapa user yang terdampak satu galat, tanpa
    username (NPM untuk akun SSO), nama, email, maupun IP. Harus berada sesudah
    AuthenticationMiddleware.

    Saat Sentry aktif, integrasi Django memberi tiap request scope-nya sendiri,
    jadi id ini tidak terbawa ke request berikutnya. Saat Sentry mati (DEBUG,
    tes) scope per request itu tidak ada, dan `set_user` akan menulis ke scope
    global proses — karena itu dilewati sama sekali.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and sentry_sdk.get_client().is_active():
            sentry_sdk.set_user({"id": user.pk})
        return self.get_response(request)
