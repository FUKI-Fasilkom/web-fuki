"""Peta isi panel pengelola SIWAK.

Seluruh struktur panel — empat bagian, menu di dalamnya, kolom tabel, dan form
yang dipakai — didaftarkan di berkas ini. View di `panel_views.py` sengaja
dibuat generik dan membaca peta ini, sehingga menambah satu jenis data baru
cukup dengan menambah satu `Sumber` di sini: halaman daftar, tambah, ubah, dan
hapus langsung ada tanpa menulis view atau template baru.
"""

from dataclasses import dataclass, field
from typing import Callable

from django.db.models import Count
from django.db.models.functions import Length
from django.utils import formats

from . import panel_forms as f
from .models import (
    GaleriFoto,
    KelompokMentoring,
    KetuaSiwak,
    MabaProfile,
    Mentor,
    MentoringBenefit,
    MentoringTujuan,
    SistemMentoring,
    SiwakEvent,
    TimelineEvent,
)


@dataclass(frozen=True)
class Kolom:
    """Satu kolom di tabel daftar.

    `tipe` menentukan cara sel digambar: "teks", "panjang" (dipotong),
    "gambar", "bool" (centang/silang), "tanggal", "tag", "saklar_rsvp"
    (tombol buka/tutup RSVP), "pilih_kelompok" / "pilih_kelompok_mentor"
    (dropdown kelompok untuk peserta dan untuk mentor), atau "atur_mentor"
    (keping mentor sebuah kelompok). Lihat templat panel/_sel.html.

    `urut` diisi kunci pengurutan kalau judul kolomnya boleh diklik untuk
    mengurutkan; kuncinya harus ada di `Sumber.pengurutan`.
    """

    judul: str
    ambil: Callable
    tipe: str = "teks"
    utama: bool = False  # jadi judul kartu saat tampilan HP
    urut: str = ""


@dataclass(frozen=True)
class Sumber:
    """Satu jenis data yang bisa dikelola lewat panel."""

    slug: str
    bagian: str
    label: str
    label_jamak: str
    deskripsi: str
    model: type
    form: type
    kolom: tuple
    pencarian: tuple = ()
    kosong: str = ""
    queryset: Callable = None
    # {"kunci": (ekspresi ORM, ...)} — dipakai view saat judul kolom diklik.
    pengurutan: dict = None
    urut_awal: str = ""

    def ambil_queryset(self):
        return self.queryset() if self.queryset else self.model.objects.all()

    def kolom_urut(self):
        """Kolom yang judulnya bisa diklik; jadi isi pilihan "Urutkan" di HP."""
        return [k for k in self.kolom if k.urut]


@dataclass(frozen=True)
class Bagian:
    """Satu dari empat kotak besar di halaman depan panel."""

    slug: str
    nama: str
    deskripsi: str
    ikon: str
    menu: tuple = field(default_factory=tuple)


def _potong(nilai, batas=90):
    teks = str(nilai or "")
    return teks if len(teks) <= batas else teks[:batas].rstrip() + "…"


def _rentang_tanggal(tahapan):
    """"17 - 27 Sep 2026" untuk tahapan berhari-hari, satu tanggal untuk sehari."""
    mulai = tahapan.tanggal_mulai
    selesai = tahapan.tanggal_selesai
    if not selesai or selesai == mulai:
        return formats.date_format(mulai, "j M Y")
    if (mulai.year, mulai.month) == (selesai.year, selesai.month):
        return f"{mulai.day} - {formats.date_format(selesai, 'j M Y')}"
    return f"{formats.date_format(mulai, 'j M')} - {formats.date_format(selesai, 'j M Y')}"


def _kelompok_peserta(maba):
    """Id kelompok maba ini, jadi pilihan terpilih di dropdown kolom Kelompok."""
    peserta = getattr(maba, "peserta", None)
    return peserta.kelompok_id if peserta else None


def _saklar_rsvp(acara):
    """Dua hal yang dibutuhkan tombol RSVP: statusnya sekarang, dan nama
    acaranya untuk ditulis di kotak konfirmasi sebelum diubah."""
    return {"aktif": acara.rsvp_dibuka, "judul": acara.judul}


def _urut_nama_kelompok(awalan=""):
    """Urutan "Kelompok 2" sebelum "Kelompok 10".

    Kelompok bernomor selalu ditulis dengan pola yang sama, jadi mengurutkan
    panjang namanya lebih dulu sudah menghasilkan urutan angka yang benar —
    tanpa perlu fungsi SQL khusus yang belum tentu ada di SQLite.
    """
    return (Length(f"{awalan}nama_kelompok"), f"{awalan}nama_kelompok")


# ---------------------------------------------------------------------------
# Daftar sumber data
# ---------------------------------------------------------------------------

SUMBER = [
    # --- Bagian 1: Info SIWAK -------------------------------------------------
    Sumber(
        slug="tujuan",
        bagian="info",
        label="Tujuan Mentoring",
        label_jamak="Tujuan Mentoring",
        deskripsi="Poin-poin tujuan yang tampil di bagian “Tujuan Mentoring”.",
        model=MentoringTujuan,
        form=f.TujuanForm,
        kolom=(
            Kolom("Urutan", lambda o: o.urutan, "tag"),
            Kolom("Judul", lambda o: o.judul, utama=True),
            Kolom("Deskripsi", lambda o: _potong(o.deskripsi), "panjang"),
        ),
        pencarian=("judul", "deskripsi"),
        kosong="Belum ada tujuan mentoring yang ditulis.",
    ),
    Sumber(
        slug="benefit",
        bagian="info",
        label="Benefit Mentoring",
        label_jamak="Benefit Mentoring",
        deskripsi="Manfaat yang didapat maba, tampil sebagai kartu di halaman SIWAK.",
        model=MentoringBenefit,
        form=f.BenefitForm,
        kolom=(
            Kolom("Urutan", lambda o: o.urutan, "tag"),
            Kolom("Judul", lambda o: o.judul, utama=True),
            Kolom("Deskripsi", lambda o: _potong(o.deskripsi), "panjang"),
        ),
        pencarian=("judul", "deskripsi"),
        kosong="Belum ada benefit yang ditulis.",
    ),
    Sumber(
        slug="sistem",
        bagian="info",
        label="Poin Sistem Mentoring",
        label_jamak="Sistem Mentoring",
        deskripsi="Daftar poin cara mentoring berjalan.",
        model=SistemMentoring,
        form=f.SistemForm,
        kolom=(
            Kolom("Urutan", lambda o: o.urutan, "tag"),
            Kolom("Isi poin", lambda o: _potong(o.deskripsi, 140), utama=True),
        ),
        pencarian=("deskripsi",),
        kosong="Belum ada poin sistem mentoring.",
    ),
    Sumber(
        slug="galeri",
        bagian="info",
        label="Foto Galeri",
        label_jamak="Galeri",
        deskripsi="Foto dokumentasi yang tampil di galeri halaman SIWAK.",
        model=GaleriFoto,
        form=f.GaleriForm,
        kolom=(
            Kolom("Foto", lambda o: o.gambar, "gambar"),
            Kolom("Keterangan", lambda o: o.caption or "Tanpa keterangan", utama=True),
            Kolom("Urutan", lambda o: o.urutan, "tag"),
        ),
        pencarian=("caption",),
        kosong="Belum ada foto di galeri.",
    ),
    Sumber(
        slug="ketua",
        bagian="info",
        label="Ketua SIWAK-NG",
        label_jamak="Ketua SIWAK",
        deskripsi="Daftar ketua SIWAK-NG dari tahun ke tahun.",
        model=KetuaSiwak,
        form=f.KetuaForm,
        kolom=(
            Kolom("Foto", lambda o: o.foto, "gambar"),
            Kolom("Nama", lambda o: o.nama, utama=True),
            Kolom("Tahun", lambda o: o.tahun, "tag"),
            Kolom("Urutan", lambda o: o.urutan, "tag"),
        ),
        pencarian=("nama", "tahun"),
        kosong="Belum ada data ketua SIWAK.",
    ),

    # --- Bagian 2: Timeline SIWAK --------------------------------------------
    Sumber(
        slug="timeline",
        bagian="timeline",
        label="Tahapan Timeline",
        label_jamak="Timeline SIWAK",
        deskripsi="Rangkaian tahapan SIWAK-NG beserta tanggalnya.",
        model=TimelineEvent,
        form=f.TimelineForm,
        kolom=(
            Kolom("Tahapan", lambda o: o.judul, utama=True),
            Kolom("Kategori", lambda o: o.get_kategori_display(), "tag"),
            Kolom("Tanggal", _rentang_tanggal),
            Kolom("Status", lambda o: o.status_label, "tag"),
            Kolom("Tampil", lambda o: o.is_active, "bool"),
        ),
        pencarian=("judul", "deskripsi"),
        kosong="Belum ada tahapan timeline.",
    ),

    # --- Bagian 3: Cari Kelompok SIWAK ---------------------------------------
    Sumber(
        slug="peserta",
        bagian="kelompok",
        label="Peserta Mentoring",
        label_jamak="Peserta Mentoring",
        deskripsi="Identitas maba peserta mentoring. Kelompoknya bisa langsung diganti lewat dropdown di kolom Kelompok.",
        model=MabaProfile,
        form=f.PesertaForm,
        kolom=(
            Kolom("Nama", lambda o: o.nama_lengkap, utama=True, urut="nama"),
            Kolom("NPM", lambda o: o.npm, urut="npm"),
            Kolom("Jurusan", lambda o: o.get_jurusan_display(), "tag"),
            # Dropdown, bukan tulisan: memindahkan peserta adalah pekerjaan yang
            # paling sering dilakukan di halaman ini, jadi tidak masuk akal
            # kalau harus membuka form ubah dulu setiap kali.
            Kolom("Kelompok", _kelompok_peserta, "pilih_kelompok", urut="kelompok"),
            Kolom("Sudah login SSO", lambda o: o.user_id is not None, "bool"),
        ),
        pencarian=("nama_lengkap", "npm"),
        kosong="Belum ada peserta mentoring yang terdaftar.",
        queryset=lambda: MabaProfile.objects.select_related("peserta__kelompok", "user"),
        pengurutan={
            "nama": ("nama_lengkap",),
            "npm": ("npm",),
            "kelompok": _urut_nama_kelompok("peserta__kelompok__") + ("nama_lengkap",),
        },
        urut_awal="nama",
    ),
    Sumber(
        slug="kelompok",
        bagian="kelompok",
        label="Kelompok Mentoring",
        label_jamak="Kelompok Mentoring",
        deskripsi="Daftar kelompok beserta link grup WhatsApp-nya. Mentor kelompok bisa langsung ditambah atau dilepas dari daftar ini.",
        model=KelompokMentoring,
        form=f.KelompokForm,
        kolom=(
            Kolom("Kelompok", lambda o: o.nama_kelompok, utama=True, urut="nama"),
            Kolom("Mentor", lambda o: list(o.mentor_list.all()), "atur_mentor"),
            Kolom("Peserta", lambda o: f"{o.peserta_list.count()} / {o.kapasitas}", "tag", urut="peserta"),
            Kolom("Aktif", lambda o: o.is_active, "bool"),
        ),
        pencarian=("nama_kelompok",),
        kosong="Belum ada kelompok mentoring.",
        queryset=lambda: KelompokMentoring.objects.prefetch_related(
            "mentor_list", "peserta_list"
        ).annotate(urut_terisi=Count("peserta_list")),
        pengurutan={
            "nama": _urut_nama_kelompok(),
            # Lewat alias anotasi, bukan Count() langsung: order_by() menolak
            # agregat yang tidak pernah masuk annotate().
            "peserta": ("urut_terisi",) + _urut_nama_kelompok(),
        },
        urut_awal="nama",
    ),
    Sumber(
        slug="mentor",
        bagian="kelompok",
        label="Mentor",
        label_jamak="Mentor",
        deskripsi="Daftar nama mentor. Satu mentor memegang satu kelompok, dan kelompoknya bisa langsung diganti lewat dropdown.",
        model=Mentor,
        form=f.MentorForm,
        kolom=(
            Kolom("Nama", lambda o: o.nama, utama=True, urut="nama"),
            Kolom("NPM", lambda o: o.npm or "-"),
            Kolom("Memegang kelompok", lambda o: o.kelompok_id, "pilih_kelompok_mentor", urut="kelompok"),
        ),
        pencarian=("nama", "npm"),
        kosong="Belum ada mentor yang terdaftar.",
        queryset=lambda: Mentor.objects.select_related("kelompok"),
        pengurutan={
            "nama": ("nama",),
            "kelompok": _urut_nama_kelompok("kelompok__") + ("nama",),
        },
        urut_awal="nama",
    ),

    # --- Bagian 4: SIWAK Events ----------------------------------------------
    Sumber(
        slug="event",
        bagian="event",
        label="SIWAK Event",
        label_jamak="SIWAK Events",
        deskripsi="Acara SIWAK-NG yang tampil di halaman utama dan bisa menerima RSVP.",
        model=SiwakEvent,
        form=f.EventForm,
        kolom=(
            Kolom("Gambar", lambda o: o.gambar, "gambar"),
            Kolom("Acara", lambda o: o.judul, utama=True),
            Kolom("Tanggal", lambda o: o.tanggal, "tanggal"),
            Kolom("Lokasi", lambda o: o.lokasi or "—"),
            # Saklar, bukan sekadar penanda: status RSVP paling sering diubah
            # dari daftar ini. Tetap ada kotak konfirmasi sebelum berubah,
            # karena menutup RSVP di waktu yang salah langsung terasa di maba.
            Kolom("RSVP", _saklar_rsvp, "saklar_rsvp"),
        ),
        pencarian=("judul", "deskripsi", "lokasi"),
        kosong="Belum ada acara SIWAK.",
        queryset=lambda: SiwakEvent.objects.prefetch_related("rsvp_list"),
    ),
]

PETA_SUMBER = {s.slug: s for s in SUMBER}


def sumber_bagian(slug_bagian):
    return [s for s in SUMBER if s.bagian == slug_bagian]


def daftar_kelompok():
    """Isi dropdown kelompok, lengkap dengan hitungan terisi/kapasitas."""
    return (
        KelompokMentoring.objects.annotate(terisi=Count("peserta_list"))
        .order_by(*_urut_nama_kelompok())
    )


def daftar_mentor():
    """Isi dropdown "+ mentor". Kelompok yang sedang dipegang ikut dibawa
    supaya pengelola melihat bahwa memilih mentor itu berarti memindahkannya,
    bukan menambah kelompok kedua."""
    return Mentor.objects.select_related("kelompok")


# ---------------------------------------------------------------------------
# Empat bagian utama
# ---------------------------------------------------------------------------

BAGIAN = [
    Bagian(
        slug="info",
        nama="Info SIWAK",
        deskripsi="Semua tulisan dan foto yang tampil di halaman utama SIWAK-NG.",
        ikon="informasi",
    ),
    Bagian(
        slug="timeline",
        nama="Timeline SIWAK",
        deskripsi="Rangkaian tahapan SIWAK-NG dari pembagian kelompok sampai main event.",
        ikon="kalender",
    ),
    Bagian(
        slug="kelompok",
        nama="Cari Kelompok SIWAK",
        deskripsi="Peserta, kelompok, dan mentor — termasuk penempatan peserta dan penugasan mentornya.",
        ikon="orang",
    ),
    Bagian(
        slug="event",
        nama="SIWAK Events",
        deskripsi="Acara SIWAK-NG dan pengaturan buka-tutup RSVP-nya.",
        ikon="tiket",
    ),
]

PETA_BAGIAN = {b.slug: b for b in BAGIAN}

# Halaman khusus yang bukan CRUD biasa, ikut muncul di menu samping.
# ("slug bagian", "nama url", "label", "keterangan")
HALAMAN_KHUSUS = {
    "info": [("panel_info", "Konten Halaman Utama", "Judul header, penjelasan SIWAK & mentoring, kontak CP.")],
}
