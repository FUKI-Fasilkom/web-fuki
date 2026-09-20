"""Peta isi panel pengelola SIWAK.

Seluruh struktur panel — empat bagian, menu di dalamnya, kolom tabel, dan form
yang dipakai — didaftarkan di berkas ini. View di `panel_views.py` sengaja
dibuat generik dan membaca peta ini, sehingga menambah satu jenis data baru
cukup dengan menambah satu `Sumber` di sini: halaman daftar, tambah, ubah, dan
hapus langsung ada tanpa menulis view atau template baru.
"""

from dataclasses import dataclass, field
from typing import Callable

from django.db.models import Count, Q
from django.db.models.functions import Length
from django.utils import formats

from . import panel_forms as f
from .models import (
    AssessmentAspect,
    GaleriFoto,
    KelompokMentoring,
    KetuaSiwak,
    MahasiswaProfile,
    MentoringBenefit,
    MentoringSession,
    MentoringTujuan,
    SistemMentoring,
    SiwakEvent,
    TimelineEvent,
    Tugas,
)


@dataclass(frozen=True)
class Kolom:
    """Satu kolom di tabel daftar.

    `tipe` menentukan cara sel digambar: "teks", "panjang" (dipotong),
    "gambar", "bool" (centang/silang), "tanggal", "tag", "nomor" (urutan baris
    di daftar, ikut nomor halaman), "saklar_rsvp" (tombol buka/tutup RSVP),
    "pilih_kelompok" / "pilih_kelompok_mentor" (dropdown kelompok untuk mentee
    dan untuk mentor; keduanya menyimpan lewat satu alamat yang sama, bedanya
    hanya label dan hitungan kapasitas), "pilih_role" (dropdown role profil),
    atau "pilih_aktif". Lihat templat panel/_sel.html.

    `urut` diisi kunci pengurutan kalau judul kolomnya boleh diklik untuk
    mengurutkan; kuncinya harus ada di `Sumber.pengurutan`.
    """

    judul: str
    ambil: Callable
    tipe: str = "teks"
    utama: bool = False  # jadi judul kartu saat tampilan HP
    urut: str = ""


@dataclass(frozen=True)
class AksiBaris:
    """Tombol tambahan di ujung satu baris daftar, mis. "Pertanyaan (3)".

    `label` menerima objek barisnya supaya tombolnya bisa menyebut jumlah, dan
    `nama_url` dipanggil dengan pk objek itu.
    """

    label: Callable
    nama_url: str


@dataclass(frozen=True)
class Sumber:
    """Satu jenis data yang bisa dikelola lewat panel."""

    slug: str
    bagian: str
    label: str
    label_jamak: str
    deskripsi: str
    model: type
    form: type  # None untuk data hanya-tampil (boleh_tambah/ubah/hapus semuanya False)
    kolom: tuple
    pencarian: tuple = ()
    kosong: str = ""
    queryset: Callable = None
    # {"kunci": (ekspresi ORM, ...)} — dipakai view saat judul kolom diklik.
    pengurutan: dict = None
    urut_awal: str = ""
    # Data yang barisnya lahir/mati di tempat lain (mis. sesi mentoring dibuat
    # otomatis saat kelompok dibuat) cukup boleh diubah saja.
    boleh_tambah: bool = True
    boleh_ubah: bool = True
    boleh_hapus: bool = True
    # Tombol tambahan per baris, di samping Ubah dan Hapus.
    aksi_baris: tuple = ()

    def ambil_queryset(self):
        return self.queryset() if self.queryset else self.model.objects.all()

    def punya_aksi(self):
        """Kolom "Aksi" hanya digambar kalau ada tombol yang bisa ditekan."""
        return bool(self.boleh_ubah or self.boleh_hapus or self.aksi_baris)

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


def _nama_mentor(kelompok):
    """Nama mentor kelompok ini. Dibaca dari `anggota` yang sudah di-prefetch
    (bukan `kelompok.daftar_mentor`, yang menembak satu query per baris)."""
    nama = [
        a.nama_lengkap
        for a in kelompok.anggota.all()
        if a.role == MahasiswaProfile.ROLE_MENTOR
    ]
    return ", ".join(nama) or "—"


def _jumlah_mentee(kelompok):
    return sum(a.role == MahasiswaProfile.ROLE_MENTEE for a in kelompok.anggota.all())


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
    # Urutan menunya: Profile -> Mentee -> Mentor -> Kelompok.
    Sumber(
        slug="profil",
        bagian="kelompok",
        label="Profile",
        label_jamak="Profile",
        deskripsi=(
            "Semua akun yang pernah login lewat SSO UI. Role-nya kosong sampai "
            "dipilih di sini: Mentee masuk ke daftar Mentee, Mentor ke daftar Mentor."
        ),
        model=MahasiswaProfile,
        form=None,
        # Hanya tampilan: profil lahir dari login SSO dan identitasnya berasal
        # dari sana. Satu-satunya yang disunting pengelola adalah role, lewat
        # dropdown di daftarnya.
        boleh_tambah=False,
        boleh_ubah=False,
        boleh_hapus=False,
        kolom=(
            Kolom("No", lambda o: None, "nomor"),
            Kolom("Nama", lambda o: o.nama_lengkap, utama=True, urut="nama"),
            Kolom("NPM", lambda o: o.npm, urut="npm"),
            Kolom("Role", lambda o: o.role, "pilih_role", urut="role"),
        ),
        pencarian=("nama_lengkap", "npm"),
        kosong="Belum ada akun yang login.",
        pengurutan={
            "nama": ("nama_lengkap",),
            "npm": ("npm",),
            "role": ("role", "nama_lengkap"),
        },
        urut_awal="nama",
    ),
    Sumber(
        slug="peserta",
        bagian="kelompok",
        label="Mentee",
        label_jamak="Mentee",
        deskripsi="Profil ber-role Mentee. Kelompoknya bisa langsung diganti lewat dropdown di kolom Kelompok.",
        model=MahasiswaProfile,
        form=f.PesertaForm,
        kolom=(
            Kolom("Nama", lambda o: o.nama_lengkap, utama=True, urut="nama"),
            Kolom("NPM", lambda o: o.npm, urut="npm"),
            Kolom("Jurusan", lambda o: o.get_jurusan_display(), "tag"),
            # Dropdown, bukan tulisan: memindahkan mentee adalah pekerjaan yang
            # paling sering dilakukan di halaman ini, jadi tidak masuk akal
            # kalau harus membuka form ubah dulu setiap kali.
            Kolom("Kelompok", lambda o: o.kelompok_id, "pilih_kelompok", urut="kelompok"),
            Kolom("Sudah login SSO", lambda o: o.user_id is not None, "bool"),
        ),
        pencarian=("nama_lengkap", "npm"),
        kosong="Belum ada mentee. Pilih role Mentee untuk sebuah akun di daftar Profile.",
        queryset=lambda: MahasiswaProfile.objects.filter(
            role=MahasiswaProfile.ROLE_MENTEE
        ).select_related("kelompok", "user"),
        pengurutan={
            "nama": ("nama_lengkap",),
            "npm": ("npm",),
            "kelompok": _urut_nama_kelompok("kelompok__") + ("nama_lengkap",),
        },
        urut_awal="nama",
    ),
    Sumber(
        slug="mentor",
        bagian="kelompok",
        label="Mentor",
        label_jamak="Mentor",
        deskripsi="Daftar mentor. Satu mentor memegang satu kelompok, dan kelompoknya bisa langsung diganti lewat dropdown. Mentor yang barisnya disiapkan di sini tersambung ke akunnya begitu login SSO.",
        model=MahasiswaProfile,
        form=f.MentorForm,
        kolom=(
            Kolom("Nama", lambda o: o.nama_lengkap, utama=True, urut="nama"),
            Kolom("NPM", lambda o: o.npm),
            Kolom("Memegang kelompok", lambda o: o.kelompok_id, "pilih_kelompok_mentor", urut="kelompok"),
            Kolom("Sudah login SSO", lambda o: o.user_id is not None, "bool"),
        ),
        pencarian=("nama_lengkap", "npm"),
        kosong="Belum ada mentor yang terdaftar.",
        queryset=lambda: MahasiswaProfile.objects.filter(
            role=MahasiswaProfile.ROLE_MENTOR
        ).select_related("kelompok", "user"),
        pengurutan={
            "nama": ("nama_lengkap",),
            "kelompok": _urut_nama_kelompok("kelompok__") + ("nama_lengkap",),
        },
        urut_awal="nama",
    ),
    Sumber(
        slug="kelompok",
        bagian="kelompok",
        label="Kelompok Mentoring",
        label_jamak="Kelompok Mentoring",
        deskripsi="Daftar kelompok beserta link grup WhatsApp-nya. Mentor dan peserta ditempatkan lewat dropdown di daftar Mentor dan daftar Mentee.",
        model=KelompokMentoring,
        form=f.KelompokForm,
        kolom=(
            Kolom("Kelompok", lambda o: o.nama_kelompok, utama=True, urut="nama"),
            Kolom("Mentor", _nama_mentor),
            Kolom("Mentee", lambda o: f"{_jumlah_mentee(o)} / {o.kapasitas}", "tag", urut="peserta"),
            Kolom("Aktif", lambda o: o.is_active, "bool"),
        ),
        pencarian=("nama_kelompok",),
        kosong="Belum ada kelompok mentoring.",
        queryset=lambda: KelompokMentoring.objects.prefetch_related("anggota").annotate(
            urut_terisi=Count("anggota", filter=Q(anggota__role=MahasiswaProfile.ROLE_MENTEE))
        ),
        pengurutan={
            "nama": _urut_nama_kelompok(),
            # Lewat alias anotasi, bukan Count() langsung: order_by() menolak
            # agregat yang tidak pernah masuk annotate().
            "peserta": ("urut_terisi",) + _urut_nama_kelompok(),
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
        aksi_baris=(
            AksiBaris(lambda o: f"RSVP ({o.rsvp_list.count()})", "siwak:panel_rsvp"),
        ),
        pencarian=("judul", "deskripsi", "lokasi"),
        kosong="Belum ada acara SIWAK.",
        queryset=lambda: SiwakEvent.objects.prefetch_related("rsvp_list"),
    ),

    # --- Bagian 5: Mentoring ---------------------------------------------------
    Sumber(
        slug="sesi",
        bagian="mentoring",
        label="Sesi Mentoring",
        label_jamak="Sesi Mentoring",
        deskripsi=(
            "Empat sesi tiap kelompok dibuat otomatis. Di sini tanggal, catatan, dan status "
            "aktifnya diatur — mentor baru bisa mengisi presensi kalau sesinya aktif."
        ),
        model=MentoringSession,
        form=f.SesiForm,
        # Sesi lahir bersama kelompoknya lewat signal dan nomornya dikunci 1-4,
        # jadi yang masuk akal di sini cuma mengubah isinya.
        boleh_tambah=False,
        boleh_hapus=False,
        kolom=(
            Kolom("Kelompok", lambda o: o.kelompok.nama_kelompok, utama=True, urut="kelompok"),
            Kolom("Sesi", lambda o: o.judul, urut="sesi"),
            Kolom("Tanggal", lambda o: o.tanggal, "tanggal", urut="tanggal"),
            # Dropdown, bukan penanda: membuka sesi berikutnya untuk semua
            # kelompok adalah pekerjaan paling sering di halaman ini, dan
            # membuka form ubah satu per satu hanya untuk satu centang jelas
            # tidak masuk akal.
            Kolom("Aktif", lambda o: o.is_active, "pilih_aktif"),
            Kolom("Catatan", lambda o: o.catatan or "—", "panjang"),
        ),
        pencarian=("kelompok__nama_kelompok",),
        kosong="Sesi mentoring muncul otomatis begitu kelompok mentoring dibuat.",
        queryset=lambda: MentoringSession.objects.select_related("kelompok"),
        pengurutan={
            "kelompok": _urut_nama_kelompok("kelompok__") + ("nomor",),
            # Dikelompokkan per nomor sesi (semua "Sesi 1" berdampingan), baru
            # per kelompok di dalamnya.
            "sesi": ("nomor",) + _urut_nama_kelompok("kelompok__"),
            "tanggal": ("tanggal", "nomor"),
        },
        urut_awal="kelompok",
    ),
    Sumber(
        slug="aspek",
        bagian="mentoring",
        label="Aspek Penilaian",
        label_jamak="Aspek Penilaian",
        deskripsi=(
            "Daftar aspek yang dinilai mentor. Menambah aspek di sini langsung menambah "
            "kolom nilai di halaman penilaian mentor."
        ),
        model=AssessmentAspect,
        form=f.AspekForm,
        kolom=(
            Kolom("Nama", lambda o: o.nama, utama=True, urut="nama"),
            Kolom("Aktif", lambda o: o.is_active, "bool"),
        ),
        kosong="Belum ada aspek penilaian. Mentor belum bisa memberi nilai sampai ada minimal satu.",
        queryset=lambda: AssessmentAspect.objects.order_by("urutan", "nama"),
        # Tanpa urut_awal: daftarnya mengikuti urutan rubrik di model, sama
        # dengan yang dilihat mentor saat menilai.
        pengurutan={"nama": ("nama",)},
    ),
    Sumber(
        slug="tugas",
        bagian="mentoring",
        label="Tugas",
        label_jamak="Tugas",
        deskripsi="Tugas mentoring beserta pertanyaannya. Satu tugas berlaku untuk semua kelompok.",
        model=Tugas,
        form=f.TugasForm,
        kolom=(
            Kolom("Judul", lambda o: o.judul_tugas, utama=True, urut="judul"),
            Kolom("Deadline", lambda o: o.deadline, "tanggal", urut="deadline"),
            Kolom("Aktif", lambda o: o.is_active, "bool"),
            Kolom("Pertanyaan", lambda o: o.jumlah_pertanyaan),
            Kolom("Submission", lambda o: o.jumlah_submission),
        ),
        aksi_baris=(
            AksiBaris(lambda o: f"Pertanyaan ({o.jumlah_pertanyaan})", "siwak:panel_pertanyaan"),
            AksiBaris(lambda o: "Lihat Jawaban / Submissions", "siwak:panel_jawaban"),
        ),
        kosong="Belum ada tugas mentoring.",
        queryset=lambda: Tugas.objects.annotate(
            jumlah_pertanyaan=Count("questions", distinct=True),
            jumlah_submission=Count("submissions", distinct=True),
        ),
        pengurutan={"judul": ("judul_tugas",), "deadline": ("deadline",)},
        urut_awal="deadline",
    ),
]

PETA_SUMBER = {s.slug: s for s in SUMBER}


def sumber_bagian(slug_bagian):
    return [s for s in SUMBER if s.bagian == slug_bagian]


def daftar_kelompok():
    """Isi dropdown kelompok, lengkap dengan hitungan terisi/kapasitas.

    Bentuknya (nilai, label, detail) sama dengan `daftar_role()`, supaya satu
    templat dropdown (`_dropdown_pilih.html`) melayani keduanya."""
    kelompok = (
        KelompokMentoring.objects.annotate(
            terisi=Count("anggota", filter=Q(anggota__role=MahasiswaProfile.ROLE_MENTEE))
        )
        .order_by(*_urut_nama_kelompok())
    )
    return [
        {"nilai": k.pk, "label": k.nama_kelompok, "detail": f"{k.terisi}/{k.kapasitas}"}
        for k in kelompok
    ]


def daftar_role():
    """Isi dropdown role di daftar Profile."""
    return [{"nilai": nilai, "label": label} for nilai, label in MahasiswaProfile.ROLE_CHOICES]


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
        deskripsi="Profile, mentee, mentor, dan kelompok — termasuk role dan penempatan kelompoknya.",
        ikon="orang",
    ),
    Bagian(
        slug="event",
        nama="SIWAK Events",
        deskripsi="Acara SIWAK-NG dan pengaturan buka-tutup RSVP-nya.",
        ikon="tiket",
    ),
    Bagian(
        slug="mentoring",
        nama="Mentoring",
        deskripsi="Sesi mentoring, aspek penilaian, dan tugas beserta pertanyaannya.",
        ikon="tugas",
    ),
]

PETA_BAGIAN = {b.slug: b for b in BAGIAN}

# Halaman khusus yang bukan CRUD biasa, ikut muncul di menu samping.
# ("slug bagian", "nama url", "label", "keterangan")
HALAMAN_KHUSUS = {
    "info": [("panel_info", "Konten Halaman Utama", "Judul header, penjelasan SIWAK & mentoring, kontak CP.")],
}
