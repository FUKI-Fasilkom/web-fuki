"""Mesin panel pengelola yang dipakai bersama lebih dari satu panel.

Berkas ini tidak tahu apa-apa soal SIWAK maupun Kontrol Internal. Isinya tiga
hal yang sama persis dibutuhkan setiap panel:

  * bentuk datanya (`Bagian`, `Sumber`, `Kolom`, `AksiBaris`, `Saringan`) —
    satu panel dideklarasikan, bukan ditulis sebagai view per menu;
  * `PanelForm`, yang menempelkan kelas Tailwind ke widget sesuai jenisnya
    sehingga gaya isian ditulis sekali saja;
  * penolong daftar (pencarian sudah ada di `siwak/utils.py`): penyaring,
    pengurutan, sel tabel, dan tombol per baris.

Yang memakainya sekarang: panel SIWAK (`siwak/panel.py`, `siwak/panel_views.py`)
dan panel Kontrol Internal (`ki/panel.py`, `ki/panel_views.py`). Templatnya pun
dipakai bersama — lihat `siwak/templates/siwak/panel/`, yang seluruh alamatnya
datang dari konteks, bukan di-hardcode ke salah satu panel.
"""

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode

from django import forms
from django.db.models import F

PER_HALAMAN = 25

ISIAN = (
    "w-full rounded-xl border-2 border-gold-light bg-white px-4 py-3 text-[15px] text-navy "
    "placeholder-navy-400/60 transition focus:border-gold focus:outline-none "
    "focus:ring-4 focus:ring-gold/25"
)
PILIHAN = ISIAN + " appearance-none pr-10"
CENTANG = (
    "h-5 w-5 shrink-0 cursor-pointer rounded border-2 border-gold-light "
    "accent-navy focus:ring-2 focus:ring-gold/40"
)
BERKAS = (
    "w-full cursor-pointer rounded-xl border-2 border-dashed border-gold-light bg-cream-50 "
    "px-4 py-3 text-sm text-navy file:mr-3 file:rounded-lg file:border-0 file:bg-navy "
    "file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-navy-700"
)


# ---------------------------------------------------------------------------
# Bentuk data sebuah panel
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Kolom:
    """Satu kolom di tabel daftar.

    `tipe` menentukan cara sel digambar: "teks", "panjang" (dipotong),
    "gambar", "bool" (centang/silang), "tanggal", "tag", "status_presensi"
    (lencana Hadir/Izin/Tidak Hadir; nilainya pasangan (status, label)), "nomor" (urutan baris
    di daftar, ikut nomor halaman), "saklar_rsvp" (tombol buka/tutup RSVP),
    "pilih_kelompok" / "pilih_kelompok_mentor" (dropdown kelompok untuk mentee
    dan untuk mentor; keduanya menyimpan lewat satu alamat yang sama, bedanya
    hanya label dan hitungan kapasitas), "pilih_role" (dropdown role profil),
    "pilih_aktif", atau penyunting teks "isi_link" (link grup WhatsApp kelompok)
    dan "isi_npm" (NPM mentor). Lihat templat panel/_sel.html.

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
    `nama_url` dipanggil dengan pk objek itu — atau dengan hasil `pk(objek)`
    kalau tombolnya menuju objek lain, mis. mentee dari sebuah baris presensi.
    `bawa_kembali` menyisipkan alamat daftar yang sedang dibuka (lengkap dengan
    pencarian dan urutannya) sebagai `?next=`, supaya halaman tujuan bisa
    mengembalikan pengelola ke sana.
    """

    label: Callable
    nama_url: str
    pk: Callable = None
    bawa_kembali: bool = False


@dataclass(frozen=True)
class Saringan:
    """Satu dropdown penyaring di atas tabel daftar, dibaca dari `?<kunci>=`.

    `pilihan` dipanggil setiap kali halaman dibuka dan mengembalikan
    [(nilai, label)]; `lookup` adalah field ORM yang dicocokkan dengan nilai
    terpilih. Nilai yang tidak ada di pilihan diabaikan, jadi alamat yang
    diketik asal-asalan tidak pernah sampai ke query sebagai teks bebas.
    """

    kunci: str
    label: str
    pilihan: Callable
    lookup: str


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
    # Dropdown penyaring (kelompok, sesi, ...) di samping kotak cari.
    saringan: tuple = ()

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
    """Satu kelompok menu di panel — satu kotak besar di halaman depannya."""

    slug: str
    nama: str
    deskripsi: str
    ikon: str


# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------

class PanelForm(forms.ModelForm):
    """Induk semua form panel: menyeragamkan tampilan widget.

    Setiap field baru yang ditambahkan ke model otomatis ikut bergaya benar
    tanpa disentuh lagi.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            widget = field.widget

            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", CENTANG)
                continue

            if isinstance(widget, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                # attrs di sini menempel ke setiap kotak centang anaknya.
                widget.attrs.setdefault("class", CENTANG)
                continue

            if isinstance(widget, forms.ClearableFileInput):
                widget.attrs.setdefault("class", BERKAS)
                continue

            if isinstance(widget, forms.SelectMultiple):
                widget.attrs.setdefault("class", ISIAN)
                continue

            if isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", PILIHAN)
                continue

            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 4)
                widget.attrs.setdefault("class", ISIAN)
                continue

            if isinstance(widget, forms.DateTimeInput):
                # DateTimeInput bukan turunan DateInput, jadi harus diurus
                # sendiri — tanpa ini deadline tugas jadi kotak teks biasa.
                widget.input_type = "datetime-local"
                widget.format = "%Y-%m-%dT%H:%M"
                field.input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
                widget.attrs.setdefault("class", ISIAN)
                continue

            if isinstance(widget, forms.TimeInput):
                # Sama alasannya dengan DateInput: tanpa ini jam kegiatan jadi
                # kotak teks biasa dan nilai lama tidak terbaca sebagai jam.
                widget.input_type = "time"
                widget.format = "%H:%M"
                field.input_formats = ["%H:%M", "%H:%M:%S"]
                widget.attrs.setdefault("class", ISIAN)
                continue

            if isinstance(widget, forms.DateInput):
                # Tanpa dua baris ini pemilih tanggal bawaan browser tidak muncul
                # dan nilai lama tidak terbaca sebagai tanggal saat form dibuka.
                widget.input_type = "date"
                widget.format = "%Y-%m-%d"

            widget.attrs.setdefault("class", ISIAN)


# ---------------------------------------------------------------------------
# Penyaring
# ---------------------------------------------------------------------------

def terapkan_saringan(qs, sumber, request):
    """Terapkan dropdown penyaring milik `sumber` dari alamat halaman.

    Mengembalikan queryset tersaring, dropdown siap render, dan apakah ada
    penyaring yang aktif. Nilai dicocokkan dengan pilihannya lebih dulu: nilai
    yang tidak dikenal diabaikan, bukan dikirim ke query.
    """
    dropdown = []
    aktif = False
    for saringan in sumber.saringan:
        pilihan = [(str(nilai), label) for nilai, label in saringan.pilihan()]
        nilai = (request.GET.get(saringan.kunci) or "").strip()
        if nilai not in dict(pilihan):
            nilai = ""
        if nilai:
            qs = qs.filter(**{saringan.lookup: nilai})
            aktif = True
        dropdown.append({
            "kunci": saringan.kunci,
            "label": saringan.label,
            "pilihan": pilihan,
            "terpilih": nilai,
        })
    return qs, dropdown, aktif


# ---------------------------------------------------------------------------
# Pengurutan daftar
# ---------------------------------------------------------------------------

def _arah(ekspresi, turun):
    """Beri arah pada satu butir pengurutan. `nulls_last` dipakai di kedua arah
    supaya baris yang belum punya kelompok selalu jatuh di bawah, bukan
    menumpuk di baris teratas saat diurutkan menurun."""
    if isinstance(ekspresi, str):
        ekspresi = F(ekspresi)
    return ekspresi.desc(nulls_last=True) if turun else ekspresi.asc(nulls_last=True)


def url_urut(request, kunci, turun):
    """Alamat daftar ini dengan urutan tertentu, tanpa kehilangan pencarian."""
    params = {
        k: v for k, v in request.GET.items()
        if k not in ("urut", "arah", "page") and v
    }
    params["urut"] = kunci
    if turun:
        params["arah"] = "turun"
    return f"?{urlencode(params)}"


def terapkan_urutan(qs, sumber, request):
    """Terapkan urutan pilihan pengguna; kembalikan queryset + kunci + arahnya."""
    if not sumber.pengurutan:
        return qs, "", False

    kunci = request.GET.get("urut") or sumber.urut_awal
    if kunci not in sumber.pengurutan:
        kunci = sumber.urut_awal
    turun = request.GET.get("arah") == "turun"

    ekspresi = sumber.pengurutan.get(kunci)
    if not ekspresi:
        return qs, "", turun
    return qs.order_by(*[_arah(e, turun) for e in ekspresi]), kunci, turun


def kepala_kolom(sumber, request, kunci_urut, turun):
    """Judul kolom tabel. Yang bisa diurutkan jadi tautan: sekali klik =
    menaik, klik lagi pada kolom yang sama = menurun."""
    kepala = []
    for kolom in sumber.kolom:
        aktif = bool(kolom.urut) and kolom.urut == kunci_urut
        kepala.append({
            "judul": kolom.judul,
            "bisa_urut": bool(kolom.urut),
            "aktif": aktif,
            "turun": turun if aktif else False,
            "url": url_urut(request, kolom.urut, (not turun) if aktif else False) if kolom.urut else "",
        })
    return kepala


def pilihan_urut(sumber, request, kunci_urut, turun):
    """Isi dropdown "Urutkan" versi HP: tampilan kartu tidak punya judul kolom
    untuk diklik, jadi pilihan yang sama disediakan sebagai satu dropdown."""
    pilihan = []
    for kolom in sumber.kolom_urut():
        for arah_turun, kata_arah in ((False, "A-Z"), (True, "Z-A")):
            pilihan.append({
                "label": f"{kolom.judul} ({kata_arah})",
                "url": url_urut(request, kolom.urut, arah_turun),
                "terpilih": kolom.urut == kunci_urut and arah_turun == turun,
            })
    return pilihan


# ---------------------------------------------------------------------------
# Baris tabel
# ---------------------------------------------------------------------------

def sel_baris(obj, sumber, nomor, url_sel=None, reverse_url=None):
    """Ubah satu objek jadi daftar sel siap render.

    `nomor` = urutan baris ini di seluruh daftar (bukan di halamannya), dipakai
    kolom bertipe "nomor". `url_sel` memetakan tipe kolom yang isinya penyunting
    kecil (dropdown, isian inline) ke nama URL penyimpannya; alamatnya
    bergantung pada baris, jadi dihitung di sini, bukan di templat.
    """
    daftar = []
    for k in sumber.kolom:
        butir = {
            "judul": k.judul, "tipe": k.tipe,
            "nilai": nomor if k.tipe == "nomor" else k.ambil(obj),
            "utama": k.utama, "pk": obj.pk,
        }
        nama_url = (url_sel or {}).get(k.tipe)
        if nama_url:
            butir["url"] = reverse_url(nama_url, args=[obj.pk])
        daftar.append(butir)
    return daftar


def aksi_baris(obj, sumber, reverse_url):
    """Tombol tambahan baris ini — labelnya boleh menghitung isi objeknya."""
    return [
        {
            "label": a.label(obj),
            "url": reverse_url(a.nama_url, args=[a.pk(obj) if a.pk else obj.pk]),
            "bawa_kembali": a.bawa_kembali,
        }
        for a in sumber.aksi_baris
    ]
