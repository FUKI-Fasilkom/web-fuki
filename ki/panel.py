"""Peta isi panel Kontrol Internal.

Panel ini sengaja hanya punya SATU menu: Kegiatan. Bentuk `Bagian`/`Sumber`/
`Kolom`/`Saringan` dan seluruh penolong daftarnya datang dari `main/panel.py`,
yang sama dipakai panel SIWAK — jadi tabel, pencarian, penyaring, pengurutan,
dan formnya berperilaku dan tampil persis sama di kedua panel.
"""

from django.utils import formats

from birdep.models import BirDep
from kegiatan.models import Kegiatan
from main.panel import Bagian, Kolom, Saringan, Sumber

from . import forms as f

BAGIAN_KEGIATAN = Bagian(
    slug="kegiatan",
    nama="Kontrol Internal",
    deskripsi="Kegiatan FUKI yang tampil di halaman Kegiatan dan di beranda.",
    ikon="kalender",
)


def _pilihan_kategori():
    return Kegiatan.KATEGORI_CHOICES


def _pilihan_tipe():
    return Kegiatan.TIPE_CHOICES


def _pilihan_birdep():
    return [
        (b.pk, b.nama)
        for b in BirDep.objects.filter(is_active=True).order_by("urutan", "nama")
    ]


def _jam(kegiatan):
    """"13.00 - 15.00", "13.00", atau "—" — jam kegiatan sekarang opsional."""
    if not kegiatan.start_time:
        return "—"
    mulai = formats.time_format(kegiatan.start_time, "H.i")
    if not kegiatan.end_time:
        return mulai
    return f"{mulai} - {formats.time_format(kegiatan.end_time, 'H.i')}"


SUMBER_KEGIATAN = Sumber(
    slug="kegiatan",
    bagian="kegiatan",
    label="Kegiatan",
    label_jamak="Kegiatan",
    deskripsi=(
        "Semua kegiatan FUKI. Yang disimpan di sini langsung tampil di halaman "
        "Kegiatan dan di bagian “Upcoming Event” beranda. Jam, lokasi, kontak, dan "
        "link pendaftaran boleh dikosongkan — yang kosong tidak ditampilkan."
    ),
    model=Kegiatan,
    form=f.KegiatanPanelForm,
    kolom=(
        Kolom("Judul", lambda o: o.judul, utama=True, urut="judul"),
        Kolom("Kategori", lambda o: o.get_kategori_display(), "tag", urut="kategori"),
        # Nama penyelenggaranya, bukan label tipenya: untuk tipe Biro /
        # Departemen yang berguna adalah nama BirDep-nya, bukan kata "BirDep".
        Kolom("Penyelenggara", lambda o: o.penyelenggara, "tag", urut="penyelenggara"),
        Kolom("Tanggal", lambda o: o.tanggal, "tanggal", urut="tanggal"),
        Kolom("Jam", _jam),
        Kolom("Lokasi", lambda o: o.lokasi or "—"),
        Kolom("Link pendaftaran", lambda o: bool(o.link_registrasi), "bool"),
    ),
    pencarian=("judul", "deskripsi", "lokasi", "birdep__nama"),
    saringan=(
        Saringan("kategori", "Kategori", _pilihan_kategori, "kategori"),
        Saringan("tipe", "Penyelenggara", _pilihan_tipe, "tipe"),
        Saringan("birdep", "Biro / Departemen", _pilihan_birdep, "birdep_id"),
    ),
    kosong="Belum ada kegiatan yang didaftarkan.",
    # select_related: kolom Penyelenggara membaca BirDep lewat Kegiatan.penyelenggara.
    queryset=lambda: Kegiatan.objects.select_related("birdep"),
    pengurutan={
        "judul": ("judul",),
        "kategori": ("kategori", "tanggal"),
        # Dalam satu tipe, BirDep diurutkan per nama supaya kegiatan satu
        # departemen berkumpul.
        "penyelenggara": ("tipe", "birdep__nama", "tanggal"),
        "tanggal": ("tanggal",),
    },
    urut_awal="tanggal",
)

SUMBER = [SUMBER_KEGIATAN]
