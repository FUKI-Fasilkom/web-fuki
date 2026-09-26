import os
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

# Jurusan yang tersedia di Fasilkom UI. Dipakai di form "Cari Kelompok" (PRD 4.3)
# dan di profil peserta mentoring.
JURUSAN_CHOICES = [
    ("IK", "Ilmu Komputer"),
    ("SI", "Sistem Informasi"),
    ("KA", "Kecerdasan Artifisial"),
    ("IK-IUP", "Ilmu Komputer (International Undergraduate Program)"),
]


class Profile(models.Model):
    """Profil tunggal setiap orang di program mentoring (PRD 7 - Authentication).

    Satu baris ini menggantikan MabaProfile + PesertaMentoring + Mentor. `role`
    menentukan perannya di `kelompok`: mentee berarti dia peserta kelompok itu,
    mentor berarti dia yang memegangnya, dan NULL berarti belum ditentukan.

    Dibuat 1-1 dengan auth.User. Barisnya boleh disiapkan pengelola lebih dulu
    hanya dengan NPM (`user` masih kosong); saat orangnya login lewat SSO UI,
    baris itu diklaim (lihat siwak/sso.py) dan `role`/`kelompok`-nya tidak berubah.

    Namanya sengaja umum, bukan khusus mahasiswa: mentor belum tentu mahasiswa
    UI. Mentor non-SSO dibuat pengelola di panel dengan username dan password
    sendiri, jadi `npm`, `jurusan`, dan `angkatan` semuanya opsional untuk dia.
    `auth_source` yang membedakan asal akunnya.
    """

    ROLE_MENTEE = "mentee"
    ROLE_MENTOR = "mentor"
    ROLE_CHOICES = [
        (ROLE_MENTEE, "Mentee"),
        (ROLE_MENTOR, "Mentor"),
    ]

    SOURCE_SSO = "sso"
    SOURCE_LOKAL = "lokal"
    AUTH_SOURCE_CHOICES = [
        (SOURCE_SSO, "SSO UI"),
        (SOURCE_LOKAL, "Akun lokal"),
    ]

    # Awalan yang dipesan untuk username akun lokal. CAS mencocokkan User lewat
    # username, jadi awalan ini yang menjamin akun buatan pengelola tidak pernah
    # kebetulan dipakai ulang oleh login SSO orang lain.
    USERNAME_LOKAL_PREFIX = "mentor-"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profil",
        null=True,
        blank=True,
        verbose_name="Akun login",
        help_text="Terisi otomatis saat orangnya login lewat SSO UI. Boleh kosong.",
    )
    # null=True, bukan sekadar blank: mentor non-SSO tidak punya NPM sama sekali.
    # Postgres memperlakukan tiap NULL sebagai berbeda di bawah UNIQUE, jadi
    # banyak profil tanpa NPM tetap sah — asal tidak ada yang menyimpan "" (lihat
    # normalisasi di save()).
    npm = models.CharField(
        max_length=20, unique=True, null=True, blank=True, verbose_name="NPM"
    )
    nama_lengkap = models.CharField(max_length=200, verbose_name="Nama Lengkap")
    # blank=True: mentor yang disiapkan pengelola sebelum login belum punya jurusan;
    # SSO yang mengisinya nanti.
    jurusan = models.CharField(
        max_length=10, choices=JURUSAN_CHOICES, blank=True, verbose_name="Jurusan"
    )
    angkatan = models.CharField(max_length=4, blank=True, verbose_name="Angkatan")
    # NULL = belum ditentukan. Akun yang baru login belum tentu mentee, belum
    # tentu mentor; pengelola yang memilihnya lewat daftar Profile di panel.
    # Selama NULL, akun ini bukan mentee maupun mentor (tidak lolos filter role
    # di mana pun), jadi tidak ada hak akses yang ikut terbuka.
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        null=True,
        blank=True,
        default=None,
        verbose_name="Peran",
    )
    # Penanda eksplisit, bukan ditebak dari password: User buatan CAS lahir lewat
    # get_or_create() tanpa password sama sekali, dan password "" itu masih
    # dilaporkan "usable" oleh Django walau tidak pernah bisa dipakai login.
    auth_source = models.CharField(
        max_length=10,
        choices=AUTH_SOURCE_CHOICES,
        default=SOURCE_SSO,
        verbose_name="Sumber akun",
    )
    kelompok = models.ForeignKey(
        "KelompokMentoring",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="anggota",
        verbose_name="Kelompok",
        help_text="Mentee: kelompok tempat dia jadi peserta. Mentor: kelompok yang dia pegang.",
    )
    # Catatan privat tentang mentee ini. Hanya mentor kelompoknya yang boleh
    # menyuntingnya; pengurus dan mentor itu yang boleh membacanya (lihat
    # services.mentor.boleh_ubah_catatan / boleh_baca_catatan). Mentee itu
    # sendiri tidak pernah melihatnya, jadi jangan pernah menampilkannya di
    # halaman yang terbuka untuk mentee.
    notes = models.TextField(
        blank=True,
        default="",
        verbose_name="Catatan privat",
        help_text="Hanya terlihat oleh pengurus dan mentor kelompok mentee ini.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Profil"
        verbose_name_plural = "Profil"
        ordering = ["nama_lengkap"]

    def __str__(self):
        return f"{self.nama_lengkap} ({self.npm})" if self.npm else self.nama_lengkap

    def save(self, *args, **kwargs):
        # "" bukan NULL: dua profil tanpa NPM yang sama-sama menyimpan string
        # kosong akan saling menabrak unique. NULL tidak.
        self.npm = self.npm or None
        super().save(*args, **kwargs)

    @property
    def is_mentor(self):
        return self.role == self.ROLE_MENTOR

    @property
    def is_mentee(self):
        return self.role == self.ROLE_MENTEE

    @property
    def is_akun_lokal(self):
        return self.auth_source == self.SOURCE_LOKAL


class SiwakInfo(models.Model):
    """Konten singleton untuk hero & section 'Apa itu SIWAK-NG' (PRD 4.1)."""

    hero_judul = models.CharField(max_length=200, default="SIWAK-NG")
    apa_itu_deskripsi = models.TextField(blank=True, verbose_name="Deskripsi 'Apa itu SIWAK-NG'")
    apa_itu_gambar = models.ImageField(
        upload_to="siwak/info/", blank=True, null=True, verbose_name="Gambar 'Apa itu SIWAK-NG'"
    )
    mentoring_deskripsi = models.TextField(blank=True, verbose_name="Deskripsi 'Apa itu Mentoring'")
    kontak_cp = models.CharField(
        max_length=300, blank=True,
        help_text="Link WhatsApp/kontak CP SIWAK, ditampilkan saat kelompok tidak ditemukan.",
        verbose_name="Link CP SIWAK",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Info SIWAK (konten halaman utama)"
        verbose_name_plural = "Info SIWAK (konten halaman utama)"

    def __str__(self):
        return "Konten Halaman SIWAK-NG"

    def save(self, *args, **kwargs):
        # Singleton: selalu pakai pk=1 supaya admin tidak bisa membuat > 1 baris.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SiwakEvent(models.Model):
    """Event SIWAK yang ditampilkan di landing page dan dapat menerima RSVP."""

    judul = models.CharField(max_length=200)
    deskripsi = models.TextField(blank=True)
    gambar = models.ImageField(upload_to="siwak/events/", blank=True, null=True)
    tanggal = models.DateField(null=True, blank=True)
    lokasi = models.CharField(max_length=200, blank=True)
    rsvp_dibuka = models.BooleanField(default=True, verbose_name="RSVP dibuka")
    urutan = models.IntegerField(default=0)

    class Meta:
        verbose_name = "SIWAK Event"
        ordering = ["urutan", "tanggal"]

    def __str__(self):
        return self.judul


class TimelineEvent(models.Model):
    """Timeline SIWAK (PRD 4.2). Status dihitung otomatis dari tanggal."""

    KATEGORI_CHOICES = [
        ("pembagian_kelompok", "Pembagian Kelompok"),
        ("mentoring", "Timeline Mentoring & Pengumpulan Tugas"),
        ("pre_event", "Pre-Main Event"),
        ("main_event", "Main Event"),
    ]

    judul = models.CharField(max_length=200, verbose_name="Judul")
    deskripsi = models.TextField(blank=True)
    kategori = models.CharField(max_length=30, choices=KATEGORI_CHOICES, default="mentoring")
    tanggal_mulai = models.DateField(verbose_name="Tanggal Mulai")
    tanggal_selesai = models.DateField(
        null=True, blank=True,
        help_text="Kosongkan jika event hanya berlangsung 1 hari.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Timeline SIWAK"
        ordering = ["tanggal_mulai"]

    def __str__(self):
        return f"{self.tanggal_mulai} - {self.judul}"

    @property
    def status(self):
        today = timezone.localdate()
        selesai = self.tanggal_selesai or self.tanggal_mulai
        if today < self.tanggal_mulai:
            return "upcoming"
        if today > selesai:
            return "completed"
        return "ongoing"

    @property
    def status_label(self):
        return {"upcoming": "Upcoming", "ongoing": "Ongoing", "completed": "Completed"}[self.status]


class KelompokMentoring(models.Model):
    """Kelompok mentoring + link grup WhatsApp (PRD 4.3)."""

    nama_kelompok = models.CharField(max_length=100, verbose_name="Nama Kelompok")
    link_grup = models.URLField(verbose_name="Link Grup WhatsApp", blank=True)
    kapasitas = models.PositiveIntegerField(default=15, verbose_name="Kapasitas")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kelompok Mentoring"
        verbose_name_plural = "Kelompok Mentoring"
        ordering = ["nama_kelompok"]

    def __str__(self):
        return self.nama_kelompok

    # Sengaja bukan `mentor_list` / `peserta_list`: itu dulu relasi ORM sungguhan,
    # jadi memakai nama yang sama untuk property akan mengundang
    # `Count("peserta_list")` yang lolos import tapi pecah saat query.
    @property
    def daftar_mentor(self):
        return self.anggota.filter(role=Profile.ROLE_MENTOR)

    @property
    def daftar_mentee(self):
        return self.anggota.filter(role=Profile.ROLE_MENTEE)


class MentoringSession(models.Model):
    SESSION_CHOICES = [(number, f"Sesi {number}") for number in range(1, 5)]

    kelompok = models.ForeignKey(
        KelompokMentoring,
        on_delete=models.CASCADE,
        related_name="mentoring_sessions",
    )
    nomor = models.PositiveSmallIntegerField(
        choices=SESSION_CHOICES,
        editable=False,
        verbose_name="Sesi",
    )
    judul = models.CharField(
        max_length=200,
        editable=False,
        verbose_name="Nama/Sesi Mentoring",
    )
    tanggal = models.DateField(null=True, blank=True, verbose_name="Tanggal Mentoring")
    catatan = models.TextField(blank=True, verbose_name="Catatan Sesi")
    is_active = models.BooleanField(default=False, verbose_name="Aktif")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sesi Mentoring"
        verbose_name_plural = "Sesi Mentoring"
        ordering = ["kelompok", "nomor"]
        constraints = [
            models.UniqueConstraint(
                fields=["kelompok", "nomor"],
                name="unique_mentoring_session_number_per_group",
            ),
            models.CheckConstraint(
                condition=models.Q(nomor__gte=1, nomor__lte=4),
                name="mentoring_session_number_between_1_and_4",
            ),
        ]

    def save(self, *args, **kwargs):
        self.judul = f"Sesi Mentoring {self.nomor}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.kelompok} - {self.judul}"


class MentoringAttendance(models.Model):
    STATUS_HADIR = "hadir"
    STATUS_TIDAK_HADIR = "tidak_hadir"
    STATUS_IZIN = "izin"
    STATUS_CHOICES = [
        (STATUS_HADIR, "Hadir"),
        (STATUS_TIDAK_HADIR, "Tidak Hadir"),
        (STATUS_IZIN, "Izin"),
    ]

    session = models.ForeignKey(
        MentoringSession,
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    peserta = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="mentoring_attendance",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    catatan = models.CharField(max_length=300, blank=True)
    recorded_by = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"role": Profile.ROLE_MENTOR},
        related_name="recorded_attendance",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Presensi Mentee"
        verbose_name_plural = "Presensi Mentee"
        constraints = [
            models.UniqueConstraint(
                fields=["session", "peserta"],
                name="unique_attendance_per_session_participant",
            ),
        ]

    def __str__(self):
        return f"{self.peserta} - {self.session} - {self.get_status_display()}"


class AssessmentAspect(models.Model):
    nama = models.CharField(max_length=100, unique=True)
    urutan = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Aspek Penilaian"
        verbose_name_plural = "Aspek Penilaian"
        ordering = ["urutan", "nama"]

    def __str__(self):
        return self.nama


class MenteeAssessment(models.Model):
    peserta = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="assessments",
    )
    aspect = models.ForeignKey(
        AssessmentAspect,
        on_delete=models.PROTECT,
        related_name="mentee_assessments",
    )
    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name="Nilai",
    )
    catatan = models.TextField(blank=True, verbose_name="Catatan Mentor")
    assessed_by = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"role": Profile.ROLE_MENTOR},
        related_name="mentee_assessments",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Penilaian Mentee"
        verbose_name_plural = "Penilaian Mentee"
        constraints = [
            models.UniqueConstraint(
                fields=["peserta", "aspect"],
                name="unique_assessment_per_participant_aspect",
            ),
        ]

    def __str__(self):
        return f"{self.peserta} - {self.aspect}: {self.score}"


class MentorFeedback(models.Model):
    session = models.ForeignKey(
        MentoringSession,
        on_delete=models.CASCADE,
        related_name="mentee_feedback",
    )
    peserta = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="mentor_feedback",
    )
    mentor = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True,
        limit_choices_to={"role": Profile.ROLE_MENTOR},
        related_name="feedback_entries",
    )
    isi = models.TextField(verbose_name="Feedback")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Feedback Mentor"
        verbose_name_plural = "Feedback Mentor"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Feedback {self.peserta} - {self.session}"


class MentoringTujuan(models.Model):
    judul = models.CharField(max_length=100, verbose_name="Judul Tujuan")
    deskripsi = models.TextField()
    urutan = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Tujuan Mentoring"
        verbose_name_plural = "Tujuan Mentoring"
        ordering = ["urutan"]

    def __str__(self):
        return self.judul


class MentoringBenefit(models.Model):
    judul = models.CharField(max_length=100, verbose_name="Judul Benefit")
    deskripsi = models.TextField()
    urutan = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Benefit Mentoring"
        verbose_name_plural = "Benefit Mentoring"
        ordering = ["urutan"]

    def __str__(self):
        return self.judul


class SistemMentoring(models.Model):
    deskripsi = models.TextField(verbose_name="Poin Sistem Mentoring")
    urutan = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Sistem Mentoring"
        verbose_name_plural = "Sistem Mentoring"
        ordering = ["urutan"]

    def __str__(self):
        return self.deskripsi[:60]


class GaleriFoto(models.Model):
    gambar = models.ImageField(upload_to="siwak/galeri/")
    caption = models.CharField(max_length=200, blank=True)
    urutan = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Foto Galeri"
        verbose_name_plural = "Galeri"
        ordering = ["urutan"]

    def __str__(self):
        return self.caption or f"Foto #{self.pk}"


class KetuaSiwak(models.Model):
    nama = models.CharField(max_length=200, verbose_name="Nama Fungsionaris")
    tahun = models.CharField(max_length=9, verbose_name="Tahun (mis. 2025 atau 2024/2025)")
    foto = models.ImageField(upload_to="siwak/ketua/", blank=True, null=True)
    urutan = models.IntegerField(default=0, help_text="Angka lebih kecil tampil lebih dulu.")

    class Meta:
        verbose_name = "Ketua SIWAK-NG"
        verbose_name_plural = "Ketua SIWAK-NG dari Tahun ke Tahun"
        ordering = ["-tahun"]

    def __str__(self):
        return f"{self.nama} ({self.tahun})"


class FAQMentoring(models.Model):
    pertanyaan = models.CharField(max_length=300)
    jawaban = models.TextField()
    urutan = models.IntegerField(default=0)

    class Meta:
        verbose_name = "FAQ Mentoring"
        verbose_name_plural = "FAQ Mentoring"
        ordering = ["urutan"]

    def __str__(self):
        return self.pertanyaan


def tugas_upload_path(instance, filename):
    # Tidak dipakai lagi (berkas utama dihapus), tetap ada karena direferensikan
    # migrasi 0001.
    return f"siwak/tugas/{instance.tugas_id}/{instance.user_id}/{filename}"


class Tugas(models.Model):
    """Tugas mentoring (PRD 5.1)."""

    judul_tugas = models.CharField(max_length=200)
    deskripsi = models.TextField()
    deadline = models.DateTimeField()
    max_file_size_mb = models.PositiveIntegerField(
        default=10, verbose_name="Ukuran file maksimum (MB)"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    ALLOWED_EXTENSIONS = ["pdf", "docx", "jpg", "jpeg", "png"]

    class Meta:
        verbose_name = "Tugas"
        ordering = ["deadline"]

    def __str__(self):
        return self.judul_tugas

    def submission_for(self, user):
        if not user or not user.is_authenticated:
            return None
        return self.submissions.filter(user=user).first()

class Question(models.Model):
    TYPE_CHOICES = [
        ("text", "Text"),
        ("choice", "Choice"),
        ("file", "File"),
    ]

    tugas = models.ForeignKey(
        Tugas,
        on_delete=models.CASCADE,
        related_name="questions",
    )
    pertanyaan = models.TextField()
    tipe = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
    )
    urutan = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["urutan"]

    def __str__(self):
        return self.pertanyaan[:80]

class Choice(models.Model):
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="choices",
    )
    teks = models.CharField(max_length=300)
    urutan = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["urutan"]

    def __str__(self):
        return self.teks

class TugasSubmission(models.Model):
    """Submission mentee untuk satu Tugas (PRD 5.1 - Task Fields / Submission Rules)."""

    STATUS_CHOICES = [
        ("submitted", "Submitted"),
        ("late", "Late"),
    ]

    tugas = models.ForeignKey(Tugas, on_delete=models.CASCADE, related_name="submissions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tugas_submissions")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="submitted")
    submitted_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Submission Tugas"
        unique_together = [("tugas", "user")]  # Replace submission, bukan submission ganda.

    def __str__(self):
        return f"{self.tugas} - {self.user}"

    def save(self, *args, **kwargs):
        self.status = "late" if timezone.now() > self.tugas.deadline else "submitted"
        super().save(*args, **kwargs)


class AssignmentReview(models.Model):
    """Feedback mentor untuk satu pengumpulan tugas.

    Tugas tidak diberi nilai angka; satu submission punya paling banyak satu
    feedback yang disunting di tempat (tanpa riwayat versi).
    """

    submission = models.OneToOneField(
        TugasSubmission,
        on_delete=models.CASCADE,
        related_name="mentor_review",
    )
    feedback = models.TextField()
    reviewer = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True,
        limit_choices_to={"role": Profile.ROLE_MENTOR},
        related_name="assignment_reviews",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Feedback Tugas"
        verbose_name_plural = "Feedback Tugas"

    def __str__(self):
        return f"Feedback {self.submission}"


def _new_token():
    return uuid.uuid4().hex


@dataclass(frozen=True)
class JenisQR:
    """Kolom-kolom `EventRSVP` milik satu jenis QR (registrasi ulang / kupon)."""

    field_token: str
    field_status: str
    field_waktu: str
    # Nilai status yang berarti QR ini sudah dipakai (check-in / kupon ditukar).
    status_terpakai: str
    pilihan_status: list

class Answer(models.Model):
    submission = models.ForeignKey(
        TugasSubmission,
        on_delete=models.CASCADE,
        related_name="answers",
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="answers",
    )

    text_answer = models.TextField(blank=True)
    selected_choice = models.ForeignKey(
        Choice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="answers",
    )
    file_answer = models.FileField(
        upload_to="siwak/jawaban/",
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = "Jawaban Tugas"
        unique_together = [("submission", "question")]

    def __str__(self):
        return f"{self.submission} - {self.question}"

    @property
    def isi_teks(self):
        """Jawaban sebagai teks, apa pun tipenya: teks pilihan, nama berkas, atau isian."""
        if self.selected_choice_id:
            return self.selected_choice.teks
        if self.file_answer:
            return os.path.basename(self.file_answer.name)
        return self.text_answer


class EventRSVP(models.Model):
    """RSVP + QR registrasi ulang & QR kupon makan (PRD 5.2, 6.1, 6.2)."""

    ATTENDANCE_CHOICES = [
        ("hadir", "Hadir"),
        ("tidak_hadir", "Tidak Hadir"),
        ("izin", "Izin")
    ]
    QR_CHOICES = [
        ("unused", "Unused"),
        ("redeemed", "Redeemed"),
    ]
    KEHADIRAN_STATUS_CHOICES = [
        ("hadir", "Hadir"),
        ("belum_hadir", "Belum Hadir"),
    ]

    # Izin memindai QR, dipisah per jenis QR-nya: gatekeeper cukup registrasi
    # ulang, divisi konsumsi cukup kupon makan. Superuser otomatis lolos
    # `has_perm()`, jadi perilaku lamanya (hanya superuser) tetap berlaku.
    IZIN_PINDAI = {
        "registrasi": "siwak.pindai_registrasi",
        "kupon": "siwak.pindai_kupon",
    }
    LABEL_PINDAI = {
        "registrasi": "QR registrasi ulang",
        "kupon": "QR kupon makan",
    }
    # Awalan username akun panitia SIWAK (pemindai QR) buatan panel. Fungsinya
    # sama dengan Profile.USERNAME_LOKAL_PREFIX: CAS mencocokkan User lewat
    # username, jadi awalan ini yang menjauhkan akun panitia dari login SSO
    # orang lain.
    USERNAME_PEMINDAI_PREFIX = "panitia-"

    # Satu-satunya tempat kolom tiap jenis QR ditulis: dipakai halaman pindai
    # (`qr_verify`) dan koreksi status manual dari daftar RSVP.
    JENIS_QR = {
        "registrasi": JenisQR(
            "qr_registrasi_token", "status_kehadiran", "checked_in_at", "hadir",
            KEHADIRAN_STATUS_CHOICES,
        ),
        "kupon": JenisQR("qr_kupon_token", "status_kupon", "redeemed_at", "redeemed", QR_CHOICES),
    }

    event = models.ForeignKey(SiwakEvent, on_delete=models.CASCADE, related_name="rsvp_list")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="event_rsvps")
    kehadiran = models.CharField(max_length=12, choices=ATTENDANCE_CHOICES, default="hadir")
    alasan_izin = models.CharField(max_length=300, blank=True, verbose_name="Jika Izin, Alasannya Kenapa?")
    created_at = models.DateTimeField(auto_now_add=True)

    # QR Registrasi Ulang (6.1)
    qr_registrasi_token = models.CharField(null=True, max_length=64, unique=True, default=_new_token, editable=False)
    status_kehadiran = models.CharField(max_length=12, choices=KEHADIRAN_STATUS_CHOICES, default="belum_hadir")
    checked_in_at = models.DateTimeField(null=True, blank=True)

    # QR Kupon Makan (6.2)
    qr_kupon_token = models.CharField(null=True, max_length=64, unique=True, default=_new_token, editable=False)
    status_kupon = models.CharField(null=True, max_length=10, choices=QR_CHOICES, default="unused")
    redeemed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "RSVP Event"
        unique_together = [("event", "user")]
        permissions = [
            ("pindai_registrasi", "Bisa memindai QR registrasi ulang (gatekeeper)"),
            ("pindai_kupon", "Bisa memindai QR kupon makan (konsumsi)"),
        ]

    def __str__(self):
        return f"{self.user} - {self.event}"

    def qr_terpakai(self, kind):
        jenis = self.JENIS_QR[kind]
        return getattr(self, jenis.field_status) == jenis.status_terpakai

    def ubah_status_qr(self, kind, nilai):
        """Simpan status QR `kind` beserta cap waktunya.

        Baris ini harus tetap sama bentuknya dengan hasil pindai QR: status yang
        baru dinaikkan ke "terpakai" mendapat waktu sekarang, status yang tetap
        terpakai mempertahankan waktunya, dan status yang diturunkan kehilangan
        cap waktunya — tanpa itu ada baris "belum hadir" yang menyimpan jam check-in.
        """
        jenis = self.JENIS_QR[kind]
        sudah = self.qr_terpakai(kind)
        setattr(self, jenis.field_status, nilai)
        if nilai != jenis.status_terpakai:
            setattr(self, jenis.field_waktu, None)
        elif not sudah or getattr(self, jenis.field_waktu) is None:
            setattr(self, jenis.field_waktu, timezone.now())
        self.save(update_fields=[jenis.field_status, jenis.field_waktu])


class RSVPTertunda(models.Model):
    """RSVP dari form lain untuk orang yang belum punya akun login (mentee maupun mentor).

    `EventRSVP.user` wajib terisi, sedangkan `Profile` yang disiapkan pengelola
    (mentee dari CSV pengelompokan, mentor dari CSV mentor) baru punya `user`
    setelah orangnya login SSO pertama. RSVP mereka ditampung di sini, lengkap
    dengan token QR-nya, lalu diubah jadi `EventRSVP` biasa oleh
    `siwak.services.rsvp.klaim_rsvp_tertunda` begitu profilnya diklaim (lihat
    `sync_profile`). Diisi oleh `seed_rsvp`.
    """

    event = models.ForeignKey(SiwakEvent, on_delete=models.CASCADE, related_name="rsvp_tertunda")
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="rsvp_tertunda")
    kehadiran = models.CharField(
        max_length=12, choices=EventRSVP.ATTENDANCE_CHOICES, default="hadir"
    )
    alasan_izin = models.CharField(max_length=300, blank=True)
    # Sama dengan EventRSVP: dibuat sekali di sini dan dibawa apa adanya saat
    # dipindahkan, supaya QR yang tampil nanti identik dengan yang dihitung dari RSVP ini.
    qr_registrasi_token = models.CharField(max_length=64, unique=True, default=_new_token, editable=False)
    qr_kupon_token = models.CharField(max_length=64, unique=True, default=_new_token, editable=False)
    dikirim_pada = models.DateTimeField(
        null=True, blank=True, help_text="Waktu submit di form asal; jadi `created_at` RSVP."
    )

    class Meta:
        verbose_name = "RSVP Tertunda"
        verbose_name_plural = "RSVP Tertunda"
        unique_together = [("event", "profile")]

    def __str__(self):
        return f"{self.profile} - {self.event} (tertunda)"
