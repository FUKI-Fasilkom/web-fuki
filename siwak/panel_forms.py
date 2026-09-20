"""Form untuk panel pengelola SIWAK (/siwak/admin/).

Semua form di sini mewarisi `PanelForm`, yang menempelkan kelas Tailwind ke
widget sesuai jenisnya. Gaya isian dengan demikian ditulis sekali di satu
tempat, bukan disalin ke belasan form — dan setiap field baru yang ditambahkan
ke model otomatis ikut bergaya benar tanpa disentuh lagi.
"""

from django import forms

from .models import (
    AssessmentAspect,
    Choice,
    GaleriFoto,
    KelompokMentoring,
    KetuaSiwak,
    MahasiswaProfile,
    MentoringBenefit,
    MentoringSession,
    MentoringTujuan,
    Question,
    SistemMentoring,
    SiwakEvent,
    SiwakInfo,
    TimelineEvent,
    Tugas,
)

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


class PanelForm(forms.ModelForm):
    """Induk semua form panel: menyeragamkan tampilan widget."""

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

            if isinstance(widget, forms.DateInput):
                # Tanpa dua baris ini pemilih tanggal bawaan browser tidak muncul
                # dan nilai lama tidak terbaca sebagai tanggal saat form dibuka.
                widget.input_type = "date"
                widget.format = "%Y-%m-%d"

            widget.attrs.setdefault("class", ISIAN)


# ---------------------------------------------------------------------------
# Bagian 1 — Info SIWAK
# ---------------------------------------------------------------------------

class InfoSiwakForm(PanelForm):
    class Meta:
        model = SiwakInfo
        fields = [
            "hero_judul",
            "apa_itu_deskripsi",
            "apa_itu_gambar",
            "mentoring_deskripsi",
            "kontak_cp",
        ]
        labels = {
            "hero_judul": "Judul di header halaman",
            "apa_itu_deskripsi": "Penjelasan 'Apa itu SIWAK-NG'",
            "apa_itu_gambar": "Gambar pendamping",
            "mentoring_deskripsi": "Penjelasan 'Apa itu Mentoring'",
            "kontak_cp": "Link kontak CP Fakultas",
        }
        help_texts = {
            "kontak_cp": "Ditampilkan ke maba saat kelompoknya belum ketemu. Contoh: https://wa.me/62812...",
            "apa_itu_gambar": "Format JPG atau PNG. Biarkan kosong jika tidak ingin menampilkan gambar.",
        }
        widgets = {
            "apa_itu_deskripsi": forms.Textarea(attrs={"rows": 5}),
            "mentoring_deskripsi": forms.Textarea(attrs={"rows": 5}),
        }


class TujuanForm(PanelForm):
    class Meta:
        model = MentoringTujuan
        fields = ["judul", "deskripsi", "urutan"]
        help_texts = {"urutan": "Angka lebih kecil tampil lebih dulu."}


class BenefitForm(PanelForm):
    class Meta:
        model = MentoringBenefit
        fields = ["judul", "deskripsi", "urutan"]
        help_texts = {"urutan": "Angka lebih kecil tampil lebih dulu."}


class SistemForm(PanelForm):
    class Meta:
        model = SistemMentoring
        fields = ["deskripsi", "urutan"]
        labels = {"deskripsi": "Isi poin"}
        help_texts = {"urutan": "Angka lebih kecil tampil lebih dulu."}


class GaleriForm(PanelForm):
    class Meta:
        model = GaleriFoto
        fields = ["gambar", "caption", "urutan"]
        labels = {"caption": "Keterangan foto"}
        help_texts = {
            "caption": "Boleh dikosongkan.",
            "urutan": "Angka lebih kecil tampil lebih dulu.",
        }


class KetuaForm(PanelForm):
    class Meta:
        model = KetuaSiwak
        fields = ["nama", "tahun", "foto", "urutan"]


# ---------------------------------------------------------------------------
# Bagian 2 — Timeline SIWAK
# ---------------------------------------------------------------------------

class TimelineForm(PanelForm):
    class Meta:
        model = TimelineEvent
        fields = ["judul", "kategori", "deskripsi", "tanggal_mulai", "tanggal_selesai", "is_active"]
        labels = {"is_active": "Tampilkan di halaman SIWAK"}
        help_texts = {
            "tanggal_selesai": "Kosongkan jika tahapan ini hanya berlangsung satu hari.",
        }

    def clean(self):
        data = super().clean()
        mulai, selesai = data.get("tanggal_mulai"), data.get("tanggal_selesai")
        if mulai and selesai and selesai < mulai:
            self.add_error("tanggal_selesai", "Tanggal selesai tidak boleh sebelum tanggal mulai.")
        return data


# ---------------------------------------------------------------------------
# Bagian 3 — Cari Kelompok SIWAK
# ---------------------------------------------------------------------------

class MentorForm(PanelForm):
    """Mentor = MahasiswaProfile ber-role mentor.

    Baris boleh disiapkan hanya dengan nama dan NPM; jurusan dan angkatan
    diisi SSO saat orangnya login pertama kali dan baris ini diklaim.
    """

    class Meta:
        model = MahasiswaProfile
        fields = ["nama_lengkap", "npm", "kelompok"]
        labels = {
            "nama_lengkap": "Nama mentor",
            "npm": "NPM mentor",
            "kelompok": "Memegang kelompok",
        }
        help_texts = {
            "npm": "Dipakai untuk menyambungkan baris ini dengan akun SSO mentor saat dia login.",
            "kelompok": "Satu mentor memegang satu kelompok. Boleh dikosongkan.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.role = MahasiswaProfile.ROLE_MENTOR
        self.fields["kelompok"].empty_label = "— Tanpa kelompok —"


class KelompokForm(PanelForm):
    """Form kelompok. Anggotanya (mentor dan mentee) tidak disunting di sini:
    penempatannya lewat dropdown di daftar Mentor dan daftar Peserta."""

    class Meta:
        model = KelompokMentoring
        fields = ["nama_kelompok", "link_grup", "kapasitas", "is_active"]
        labels = {"is_active": "Kelompok masih aktif"}
        help_texts = {"link_grup": "Link undangan grup WhatsApp kelompok ini."}


class PesertaForm(PanelForm):
    """Satu form untuk identitas mentee sekaligus penempatan kelompoknya.

    `kelompok` kini field MahasiswaProfile sungguhan, jadi tidak perlu lagi
    ditambahkan manual dan disimpan ke tabel kedua.
    """

    class Meta:
        model = MahasiswaProfile
        fields = ["nama_lengkap", "npm", "jurusan", "angkatan", "kelompok"]
        labels = {"kelompok": "Kelompok mentoring"}
        help_texts = {
            "npm": "Dipakai untuk mencocokkan data ini dengan akun SSO maba saat dia login.",
            "angkatan": "Contoh: 2025. Boleh dikosongkan.",
            "kelompok": "Boleh dikosongkan dulu; kelompoknya bisa diganti kapan saja lewat dropdown di daftar Peserta Mentoring.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.role = MahasiswaProfile.ROLE_MENTEE
        self.fields["kelompok"].empty_label = "— Belum ditempatkan —"
        # `jurusan` boleh kosong di model (mentor yang disiapkan sebelum login),
        # tapi mentee tetap wajib punya jurusan — "Cari Kelompok" mencarinya lewat itu.
        self.fields["jurusan"].required = True


# ---------------------------------------------------------------------------
# Bagian 4 — SIWAK Events
# ---------------------------------------------------------------------------

class EventForm(PanelForm):
    class Meta:
        model = SiwakEvent
        fields = ["judul", "deskripsi", "gambar", "tanggal", "lokasi", "rsvp_dibuka", "urutan"]
        labels = {"rsvp_dibuka": "Buka pendaftaran RSVP"}
        help_texts = {
            "rsvp_dibuka": "Saat dimatikan, maba tidak bisa RSVP baru. Yang sudah RSVP tetap bisa membuka QR-nya.",
            "urutan": "Angka lebih kecil tampil lebih dulu di halaman SIWAK.",
        }


# ---------------------------------------------------------------------------
# Bagian 5 — Mentoring
# ---------------------------------------------------------------------------


class SesiForm(PanelForm):
    """Isi satu sesi mentoring.

    Kelompok dan nomor sesi sengaja tidak ada di sini: keduanya dikunci saat
    sesi dibuat otomatis, dan memindahkan sesi ke kelompok lain akan bentrok
    dengan unique constraint (kelompok, nomor).
    """

    class Meta:
        model = MentoringSession
        fields = ["tanggal", "catatan", "is_active"]
        labels = {
            "tanggal": "Tanggal Mentoring",
            "catatan": "Catatan Sesi",
            "is_active": "Sesi aktif",
        }
        help_texts = {
            "tanggal": "Boleh dikosongkan kalau tanggalnya belum ditentukan.",
            "catatan": "Catatan untuk pengurus. Tidak tampil ke maba.",
            "is_active": "Mentor baru bisa mengisi presensi dan feedback kalau sesinya aktif.",
        }


class AspekForm(PanelForm):
    class Meta:
        model = AssessmentAspect
        fields = ["nama", "urutan", "is_active"]
        labels = {"nama": "Nama Aspek", "urutan": "Urutan", "is_active": "Aspek aktif"}
        help_texts = {
            "urutan": "Angka lebih kecil tampil lebih dulu di form penilaian mentor.",
            "is_active": (
                "Kalau dimatikan, aspek ini hilang dari form penilaian mentor, "
                "tapi nilai yang sudah masuk tetap tersimpan."
            ),
        }
        error_messages = {
            "nama": {"unique": "Sudah ada aspek penilaian dengan nama ini."},
        }


class TugasForm(PanelForm):
    class Meta:
        model = Tugas
        fields = ["judul_tugas", "deskripsi", "deadline", "max_file_size_mb", "is_active"]
        widgets = {"deadline": forms.DateTimeInput()}
        labels = {
            "judul_tugas": "Judul Tugas",
            "deskripsi": "Deskripsi",
            "deadline": "Deadline",
            "max_file_size_mb": "Ukuran file maksimum (MB)",
            "is_active": "Tugas aktif",
        }
        help_texts = {
            "deskripsi": "Satu tugas berlaku untuk semua kelompok mentoring.",
            "deadline": "Pengumpulan setelah waktu ini otomatis ditandai terlambat.",
            "is_active": "Tugas yang tidak aktif hilang dari halaman tugas maba.",
        }


class PertanyaanForm(PanelForm):
    """Satu pertanyaan di dalam sebuah tugas.

    Pilihan tipe digambar tangan di templatnya (tiga kartu, bukan dropdown),
    jadi labelnya ditulis ulang di sini dalam bahasa yang dimengerti pengurus
    tanpa mengubah nilai yang tersimpan di basis data.
    """

    TIPE_LABEL = {
        "text": "Isian teks",
        "choice": "Pilihan ganda",
        "file": "Unggah berkas",
    }
    TIPE_KETERANGAN = {
        "text": "Maba mengetik jawabannya sendiri.",
        "choice": "Maba memilih satu dari beberapa pilihan yang kamu tulis.",
        "file": "Maba mengunggah satu berkas.",
    }

    class Meta:
        model = Question
        fields = ["pertanyaan", "tipe"]
        labels = {"pertanyaan": "Pertanyaan", "tipe": "Jenis Jawaban"}
        widgets = {"pertanyaan": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipe"].choices = [
            (nilai, self.TIPE_LABEL[nilai]) for nilai, _ in Question.TYPE_CHOICES
        ]

    def kartu_tipe(self):
        """Tiga kartu pilihan tipe, siap dirender templat."""
        terpilih = self["tipe"].value() or Question.TYPE_CHOICES[0][0]
        return [
            {
                "nilai": nilai,
                "label": self.TIPE_LABEL[nilai],
                "keterangan": self.TIPE_KETERANGAN[nilai],
                "terpilih": nilai == terpilih,
            }
            for nilai, _ in Question.TYPE_CHOICES
        ]


class PilihanForm(PanelForm):
    class Meta:
        model = Choice
        fields = ["teks"]
        labels = {"teks": "Pilihan jawaban"}
