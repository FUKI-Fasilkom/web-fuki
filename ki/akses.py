"""Penjaga panel Kontrol Internal (/ki/admin/).

Aksesnya sengaja TIDAK memakai `is_staff` seperti panel SIWAK, melainkan satu
permission Django: `kegiatan.change_kegiatan`. Dengan begitu akun KI bisa dibuat
hanya untuk mengelola Kegiatan — panel SIWAK dan /admin/ tetap tertutup
untuknya — dan sebaliknya pengurus SIWAK tidak otomatis bisa mengubah Kegiatan.
Superuser lolos karena `has_perm()` selalu True untuknya.

Kunjungan salah peran melempar `AksesDitolak` milik SIWAK, bukan 403 polos,
supaya halaman penolakannya satu untuk seluruh situs dan tetap menawarkan jalan
ke bagian milik user sendiri (lihat `siwak/akses.py`).
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.urls import reverse

from siwak.akses import AksesDitolak

IZIN_KEGIATAN = "kegiatan.change_kegiatan"


def boleh_kelola_kegiatan(user):
    """Apakah `user` boleh membuka panel Kontrol Internal."""
    return bool(user and user.is_authenticated and user.has_perm(IZIN_KEGIATAN))


def ki_required(view_func):
    """Panel KI: hanya pemegang `kegiatan.change_kegiatan` (dan superuser).

    Yang belum login diarahkan ke "Login Akun Khusus", bukan ke login /admin/:
    akun KI bukan staf, jadi login admin Django akan menolaknya.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated:
            if not boleh_kelola_kegiatan(request.user):
                raise AksesDitolak("ki")
            return view_func(request, *args, **kwargs)
        return redirect_to_login(request.get_full_path(), reverse("siwak:login_khusus"))

    return _wrapped
