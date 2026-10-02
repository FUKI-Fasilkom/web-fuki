"""Siapa boleh memindai QR jenis apa (PRD 6.1 / 6.2).

Dipakai halaman pindai (`views.py`), pintu Login Akun Khusus (`auth_views.py`),
dan penentu tujuan setelah login (`sso.role_landing_url`) — karena itu tinggal
di sini, bukan di salah satu dari ketiganya.
"""

from siwak.models import EventRSVP


def boleh_memindai(user, kind=None):
    """Apakah `user` boleh memindai QR `kind` — atau QR jenis apa pun kalau
    `kind` None. Superuser selalu boleh lewat `has_perm()`; akun pemindai
    (gatekeeper, konsumsi) hanya jenis yang izinnya dia pegang."""
    if kind is None:
        return any(user.has_perm(izin) for izin in EventRSVP.IZIN_PINDAI.values())
    izin = EventRSVP.IZIN_PINDAI.get(kind)
    return bool(izin) and user.has_perm(izin)


def jenis_pindai(user):
    """Jenis QR yang boleh dipindai `user`, urut seperti EventRSVP.IZIN_PINDAI."""
    return [kind for kind in EventRSVP.IZIN_PINDAI if boleh_memindai(user, kind)]
