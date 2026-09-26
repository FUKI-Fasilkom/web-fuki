"""Pembantu monitoring Sentry: pembersih URL dan konteks user minimal.

Sengaja tidak mengimpor model apa pun, karena modul ini diimpor dari
settings.py (sebelum aplikasi Django siap).
"""

import re

import sentry_sdk

# EventScrubber Sentry hanya mengganti nilai berdasarkan NAMA KUNCI (header,
# cookie, data form, variabel lokal, ...). Ia tidak pernah membaca isi teks,
# padahal dua rahasia berupa bagian dari URL:
#   * token QR bertanda tangan di jalur /siwak/qr/<signed>/ — berlaku 30 hari
#     dan cukup untuk meng-check-in peserta atau menukar kuponnya;
#   * tiket CAS di `?ticket=ST-...` saat SSO UI mengembalikan user ke situs.
# URL itu muncul di banyak tempat, bukan hanya `request.url`/`query_string`:
# header `Referer` (halaman QR POST ke dirinya sendiri), `?next=` yang
# ter-URL-encode oleh tautan "masuk lewat SSO UI", dan `http.query` pada span
# serta breadcrumb permintaan keluar ke SSO UI (Sentry mencatat query string
# URL keluar apa adanya: `ticket` dan `service` beserta `next`-nya). Karena itu
# seluruh string di event disaring, bukan kolom tertentu.
_PEMISAH = r"(?:/|%2F|%252F)"  # "/" mentah, ter-encode, atau ter-encode dua kali
_JALUR_QR = re.compile(
    rf"({_PEMISAH}siwak{_PEMISAH}qr{_PEMISAH})(?:[\w.:-]|%(?:25)?3A)+", re.IGNORECASE
)
_TIKET_CAS = re.compile(r"((?:^|[?&]|%3F|%26)ticket(?:=|%3D))[\w.-]+", re.IGNORECASE)
DISARING = "[Filtered]"


def _samarkan(teks):
    return _TIKET_CAS.sub(rf"\g<1>{DISARING}", _JALUR_QR.sub(rf"\g<1>{DISARING}", teks))


def _samarkan_semua(nilai):
    if isinstance(nilai, str):
        return _samarkan(nilai)
    if isinstance(nilai, dict):
        return {kunci: _samarkan_semua(isi) for kunci, isi in nilai.items()}
    if isinstance(nilai, list):
        return [_samarkan_semua(isi) for isi in nilai]
    return nilai


def bersihkan_event(event, hint):
    """`before_send` / `before_send_transaction`: samarkan token QR dan tiket
    CAS di string mana pun dalam event (URL, header, span, breadcrumb, pesan)."""
    return _samarkan_semua(event)


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
