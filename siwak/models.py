import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

# Jurusan yang tersedia di Fasilkom UI. Dipakai di form "Cari Kelompok" (PRD 4.3)
# dan di profil peserta mentoring.
JURUSAN_CHOICES = [
    ("IK", "Ilmu Komputer"),
    ("SI", "Sistem Informasi"),
    ("IK-IUP", "Ilmu Komputer (International Undergraduate Program)"),
    ("SI-IUP", "Sistem Informasi (International Undergraduate Program)"),
]


class MabaProfile(models.Model):
    """Data tambahan untuk user hasil login SSO UI (PRD 7 - Authentication).

    Dibuat 1-1 dengan auth.User. `npm` dipakai sebagai username saat login.
    Lihat siwak/sso.py untuk catatan integrasi SSO UI yang sesungguhnya.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="maba_profile"
    )
    npm = models.CharField(max_length=20, unique=True, verbose_name="NPM")
    nama_lengkap = models.CharField(max_length=200, verbose_name="Nama Lengkap")
    jurusan = models.CharField(max_length=10, choices=JURUSAN_CHOICES, verbose_name="Jurusan")
    angkatan = models.CharField(max_length=4, blank=True, verbose_name="Angkatan")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Profil Maba"
        verbose_name_plural = "Profil Maba"

    def __str__(self):
        return f"{self.nama_lengkap} ({self.npm})"


class SiwakInfo(models.Model):
    """Konten singleton untuk hero & section 'Apa itu SIWAK-NG' (PRD 4.1)."""

    hero_judul = models.CharField(max_length=200, default="SIWAK-NG")
    hero_deskripsi = models.TextField(blank=True)
    apa_itu_deskripsi = models.TextField(blank=True, verbose_name="Deskripsi 'Apa itu SIWAK-NG'")
    apa_itu_gambar = models.ImageField(
        upload_to="siwak/info/", blank=True, null=True, verbose_name="Gambar 'Apa itu SIWAK-NG'"
    )
    mentoring_deskripsi = models.TextField(blank=True, verbose_name="Deskripsi 'Apa itu Mentoring'")
    cta_mentoring_link = models.CharField(
        max_length=300, blank=True, default="/siwak/kelompok/",
        verbose_name="Link tombol 'Lihat Kelompok Mentoring'",
    )
    kontak_cp = models.CharField(
        max_length=300, blank=True,
        help_text="Link WhatsApp/kontak CP Fakultas, ditampilkan saat kelompok tidak ditemukan.",
        verbose_name="Link CP Fakultas",
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
    """Pre-Event & Main Event SIWAK (PRD 4.1 'SIWAK Events' dan 5.2 RSVP)."""

    TIPE_CHOICES = [
        ("pre_event", "Pre-Event SIWAK"),
        ("main_event", "Main Event SIWAK"),
    ]

    tipe = models.CharField(max_length=20, choices=TIPE_CHOICES, unique=True)
    judul = models.CharField(max_length=200)
    deskripsi = models.TextField(blank=True)
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


class Mentor(models.Model):
    nama = models.CharField(max_length=200)

    class Meta:
        verbose_name = "Mentor"
        ordering = ["nama"]

    def __str__(self):
        return self.nama


class KelompokMentoring(models.Model):
    """Kelompok mentoring + link grup WhatsApp (PRD 4.3)."""

    nama_kelompok = models.CharField(max_length=100, verbose_name="Nama Kelompok")
    mentors = models.ManyToManyField(Mentor, related_name="kelompok_list", blank=True, verbose_name="Mentor")
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


class PesertaMentoring(models.Model):
    """Baris data peserta (mentee) yang dipakai fitur 'Cari Kelompok' (PRD 4.3).

    Diisi oleh admin lewat upload data kelompok. `user` terisi otomatis begitu
    mahasiswa terkait login lewat SSO, supaya fitur Tugas/RSVP tahu kelompok
    mana yang berlaku untuknya.
    """

    nama_lengkap = models.CharField(max_length=200)
    jurusan = models.CharField(max_length=10, choices=JURUSAN_CHOICES)
    npm = models.CharField(max_length=20, blank=True, verbose_name="NPM (opsional)")
    kelompok = models.ForeignKey(
        KelompokMentoring, on_delete=models.SET_NULL, null=True, blank=True, related_name="peserta_list"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="peserta_mentoring"
    )

    class Meta:
        verbose_name = "Peserta Mentoring"
        verbose_name_plural = "Peserta Mentoring"
        ordering = ["nama_lengkap"]
        indexes = [models.Index(fields=["nama_lengkap", "jurusan"])]

    def __str__(self):
        return f"{self.nama_lengkap} - {self.jurusan}"


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


class TugasSubmission(models.Model):
    """Submission mentee untuk satu Tugas (PRD 5.1 - Task Fields / Submission Rules)."""

    STATUS_CHOICES = [
        ("submitted", "Submitted"),
        ("late", "Late"),
    ]

    tugas = models.ForeignKey(Tugas, on_delete=models.CASCADE, related_name="submissions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tugas_submissions")
    file = models.FileField(upload_to=tugas_upload_path)
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


def _new_token():
    return uuid.uuid4().hex


class EventRSVP(models.Model):
    """RSVP + QR registrasi ulang & QR kupon makan (PRD 5.2, 6.1, 6.2)."""

    ATTENDANCE_CHOICES = [
        ("registered", "Registered"),
        ("hadir", "Hadir"),
    ]
    KUPON_CHOICES = [
        ("unused", "Unused"),
        ("redeemed", "Redeemed"),
    ]

    event = models.ForeignKey(SiwakEvent, on_delete=models.CASCADE, related_name="rsvp_list")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="event_rsvps")
    catatan = models.CharField(max_length=300, blank=True, verbose_name="Catatan tambahan (opsional)")
    created_at = models.DateTimeField(auto_now_add=True)

    # QR Registrasi Ulang (6.1)
    qr_registrasi_token = models.CharField(max_length=64, unique=True, default=_new_token, editable=False)
    status_kehadiran = models.CharField(max_length=12, choices=ATTENDANCE_CHOICES, default="registered")
    checked_in_at = models.DateTimeField(null=True, blank=True)

    # QR Kupon Makan (6.2)
    qr_kupon_token = models.CharField(max_length=64, unique=True, default=_new_token, editable=False)
    status_kupon = models.CharField(max_length=10, choices=KUPON_CHOICES, default="unused")
    redeemed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "RSVP Event"
        unique_together = [("event", "user")]

    def __str__(self):
        return f"{self.user} - {self.event}"