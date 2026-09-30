"""Potongan kecil yang dipakai bersama view SIWAK (portal, mentor, panel)."""

from django.db.models import Q
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme, urlencode


def next_aman(request):
    """`?next=` (dari POST atau GET) yang boleh dipakai, atau "" kalau tidak ada
    atau mengarah ke luar situs ini."""
    tujuan = request.POST.get("next") or request.GET.get("next") or ""
    if tujuan and url_has_allowed_host_and_scheme(
        tujuan, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return tujuan
    return ""


def kembali(request, cadangan):
    """Kembali ke halaman asal (`next`) — lengkap dengan pencarian, urutan, dan
    nomor halamannya — atau ke `cadangan` kalau tidak ada."""
    return redirect(next_aman(request) or cadangan)


def kueri_tanpa_halaman(request):
    """Query string halaman ini tanpa `page` dan isian kosong, untuk paginasi."""
    return urlencode({k: v for k, v in request.GET.items() if k != "page" and v})


def cari_teks(qs, fields, kata):
    """Saring `qs` ke baris yang salah satu `fields`-nya memuat `kata`."""
    if not kata:
        return qs
    saringan = Q()
    for nama_field in fields:
        saringan |= Q(**{f"{nama_field}__icontains": kata})
    return qs.filter(saringan)


def nama_akun(user):
    """Nama lengkap dari profil SIWAK, atau username untuk akun tanpa profil
    (akun panitia, superuser)."""
    profil = getattr(user, "profil", None)
    return profil.nama_lengkap if profil else user.username
