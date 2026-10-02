"""View panel Kontrol Internal (/ki/admin/).

Empat view CRUD di bawah melayani satu-satunya menu panel ini, Kegiatan.
Alurnya sama dengan panel SIWAK dan memakai penolong yang sama
(`main/panel.py`): pencarian, dropdown penyaring, pengurutan lewat judul kolom,
paginasi, lalu form tambah/ubah dengan tombol hapus.

Templatnya pun sama persis — `siwak/panel/daftar.html` dan `siwak/panel/form.html`
beserta sertaannya. Templat itu tidak lagi memuat alamat `siwak:` yang
di-hardcode: semua alamat dan nama panelnya datang dari `_kerangka()` di bawah,
jadi kedua panel tampil identik tanpa markup yang disalin. Letaknya masih di
bawah `siwak/templates/` karena dipakai 20-an templat SIWAK lain dengan alamat
itu; memindahkannya hanya akan menukar satu kopling dengan kopling lain.

Panel ini tidak punya halaman depan terpisah: cuma ada satu menu, jadi
`/ki/admin/` langsung berupa daftar Kegiatan.
"""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from main.panel import (
    PER_HALAMAN,
    aksi_baris,
    kepala_kolom,
    pilihan_urut,
    sel_baris,
    terapkan_saringan,
    terapkan_urutan,
)
from siwak.utils import cari_teks, kueri_tanpa_halaman

from .akses import ki_required
from .panel import BAGIAN_KEGIATAN, SUMBER, SUMBER_KEGIATAN


# ---------------------------------------------------------------------------
# Kerangka bersama
# ---------------------------------------------------------------------------

def _menu(sumber_aktif=""):
    """Menu samping. Bentuknya sama dengan panel SIWAK supaya `_menu.html` bisa
    dipakai apa adanya, hanya saja di sini isinya satu kelompok dengan satu menu."""
    return [{
        "bagian": BAGIAN_KEGIATAN,
        "url": reverse("ki:panel_daftar"),
        "butir": [
            {
                "label": s.label_jamak,
                "url": reverse("ki:panel_daftar"),
                "aktif": sumber_aktif == s.slug,
                "sorot": False,
            }
            for s in SUMBER
        ],
        "aktif": True,
    }]


def _kerangka(*, judul, sumber="", remah=(), **ekstra):
    konteks = {
        "judul_panel": judul,
        "menu": _menu(sumber),
        "remah": list(remah),
        "bagian_aktif": BAGIAN_KEGIATAN.slug,
        # Identitas panel, dibaca templat kerangka yang dipakai bersama SIWAK.
        "panel_nama": "Panel Kontrol Internal",
        "panel_url_beranda": reverse("ki:panel_daftar"),
        "panel_url_situs": reverse("kegiatan:home"),
        "panel_label_situs": "Lihat halaman Kegiatan",
    }
    konteks.update(ekstra)
    return konteks


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@ki_required
def panel_daftar(request):
    sumber = SUMBER_KEGIATAN

    kata = (request.GET.get("q") or "").strip()
    qs = cari_teks(sumber.ambil_queryset(), sumber.pencarian, kata)
    qs, saringan, ada_saringan = terapkan_saringan(qs, sumber, request)
    qs, kunci_urut, turun = terapkan_urutan(qs, sumber, request)

    halaman = Paginator(qs, PER_HALAMAN).get_page(request.GET.get("page"))
    baris = [
        {
            "obj": o,
            "pk": o.pk,
            "sel": sel_baris(o, sumber, nomor),
            "aksi": aksi_baris(o, sumber, reverse_url=reverse),
            "url_ubah": reverse("ki:panel_ubah", args=[o.pk]),
            "url_hapus": reverse("ki:panel_hapus", args=[o.pk]),
        }
        for nomor, o in enumerate(halaman.object_list, start=halaman.start_index())
    ]

    return render(request, "siwak/panel/daftar.html", _kerangka(
        judul=sumber.label_jamak,
        sumber=sumber.slug,
        remah=[(sumber.label_jamak, "")],
        sumber_data=sumber,
        kepala=kepala_kolom(sumber, request, kunci_urut, turun),
        baris=baris,
        halaman=halaman,
        kata=kata,
        saringan=saringan,
        ada_saringan=ada_saringan,
        kunci_urut=kunci_urut,
        arah_turun=turun,
        pilihan_urut=pilihan_urut(sumber, request, kunci_urut, turun),
        url_kembali=request.get_full_path(),
        kueri=kueri_tanpa_halaman(request),
        url_tambah=reverse("ki:panel_tambah"),
        url_bersih=reverse("ki:panel_daftar"),
    ))


def _simpan(request, instance=None):
    sumber = SUMBER_KEGIATAN
    ubah = instance is not None

    if request.method == "POST":
        form = sumber.form(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            obj = form.save()
            messages.success(
                request,
                f"{sumber.label} “{obj}” berhasil {'diperbarui' if ubah else 'ditambahkan'}.",
            )
            return redirect("ki:panel_daftar")
        messages.error(request, "Masih ada isian yang perlu dibetulkan.")
    else:
        form = sumber.form(instance=instance)

    judul = f"Ubah {sumber.label}" if ubah else f"Tambah {sumber.label}"
    return render(request, "siwak/panel/form.html", _kerangka(
        judul=judul,
        sumber=sumber.slug,
        remah=[
            (sumber.label_jamak, reverse("ki:panel_daftar")),
            (judul, ""),
        ],
        form=form,
        sumber_data=sumber,
        objek=instance,
        url_batal=reverse("ki:panel_daftar"),
        url_hapus=reverse("ki:panel_hapus", args=[instance.pk]) if ubah else "",
    ))


@ki_required
def panel_tambah(request):
    return _simpan(request)


@ki_required
def panel_ubah(request, pk):
    return _simpan(request, get_object_or_404(SUMBER_KEGIATAN.ambil_queryset(), pk=pk))


@ki_required
@require_POST
def panel_hapus(request, pk):
    sumber = SUMBER_KEGIATAN
    objek = get_object_or_404(sumber.ambil_queryset(), pk=pk)
    nama = str(objek)
    try:
        objek.delete()
    except ProtectedError:
        # Lebih baik bilang kenapa daripada melempar 500 ke pengurus KI.
        messages.error(
            request,
            f"{sumber.label} “{nama}” tidak bisa dihapus karena masih dipakai data lain.",
        )
        return redirect("ki:panel_daftar")
    messages.success(request, f"{sumber.label} “{nama}” berhasil dihapus.")
    return redirect("ki:panel_daftar")
