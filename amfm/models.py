"""Konten halaman Open Recruitment AM-FM (PRD 4.1).

Bentuknya sengaja meniru konten landing SIWAK (`SiwakInfo`, `MentoringBenefit`,
`TimelineEvent`): desain halamannya memakai kartu benefit dan timeline yang sama,
dan keduanya dirender oleh komponen bersama di `templates/components/`.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import models
from django.utils import timezone


class AmfmInfo(models.Model):
    """Konten singleton halaman AM-FM: hero, 'Apa itu', Tujuan, dan CTA.

    Pengaturan formulir tinggal di sini agar informasi dan pendaftaran tidak
    memiliki dua sumber konfigurasi.
    """

    hero_judul = models.CharField(max_length=100, default="AM-FM", verbose_name="Judul hero")
    hero_tagline = models.CharField(
        max_length=200, blank=True, default="#UnitePurposeAccelerateImpact",
        verbose_name="Tagline hero",
    )
    hero_deskripsi = models.TextField(
        blank=True,
        default=(
            "Wadah mahasiswa baru Fasilkom UI untuk belajar, berkarya, dan bertumbuh "
            "bersama Forum Ukhuwah dan Kajian Islam."
        ),
        verbose_name="Deskripsi hero",
    )
    apa_itu_deskripsi = models.TextField(blank=True, verbose_name="Deskripsi 'Apa itu AM-FM'")
    apa_itu_gambar = models.ImageField(
        upload_to="amfm/info/", blank=True, null=True, verbose_name="Gambar 'Apa itu AM-FM'"
    )
    tujuan = models.TextField(
        blank=True,
        default=(
            "Membangun ukhuwah antar angkatan, mengenalkan ruang kontribusi di tiap "
            "birdept, dan menyiapkan anggota muda yang siap berdampak."
        ),
        verbose_name="Tujuan AM-FM",
    )
    cta_deskripsi = models.TextField(
        blank=True, verbose_name="Deskripsi 'Siap Bergabung?'",
        help_text="Teks di kartu ajakan mendaftar di bagian bawah halaman.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    status_pendaftaran = models.CharField(
        max_length=20, default="belum_dibuka",
        choices=[("belum_dibuka", "Belum dibuka"), ("dibuka", "Dibuka"), ("ditutup", "Ditutup")],
    )
    dibuka_pada = models.DateTimeField(null=True, blank=True)
    ditutup_pada = models.DateTimeField(null=True, blank=True, verbose_name="Deadline pendaftaran")
    guidebook_url = models.URLField(blank=True, verbose_name="Link guidebook")
    kurikulum_url = models.URLField(blank=True, verbose_name="Link folder kurikulum")

    def clean(self):
        super().clean()
        if self.dibuka_pada and self.ditutup_pada and self.ditutup_pada <= self.dibuka_pada:
            raise ValidationError({"ditutup_pada": "Deadline harus setelah waktu pembukaan."})

    @property
    def status_saat_ini(self):
        if self.status_pendaftaran != "dibuka":
            return self.status_pendaftaran
        now = timezone.now()
        if self.dibuka_pada and now < self.dibuka_pada:
            return "belum_dibuka"
        if self.ditutup_pada and now >= self.ditutup_pada:
            return "ditutup"
        return "dibuka"

    class Meta:
        verbose_name = "Info AM-FM (konten halaman utama)"
        verbose_name_plural = "Info AM-FM (konten halaman utama)"

    def __str__(self):
        return "Konten Halaman AM-FM"

    def save(self, *args, **kwargs):
        # Singleton: selalu pakai pk=1 supaya admin tidak bisa membuat > 1 baris.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class AmfmBenefit(models.Model):
    judul = models.CharField(max_length=100, verbose_name="Judul Benefit")
    deskripsi = models.TextField()
    urutan = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Benefit AM-FM"
        verbose_name_plural = "Benefit AM-FM"
        ordering = ["urutan"]

    def __str__(self):
        return self.judul


class AmfmTimeline(models.Model):
    """Tahapan timeline AM-FM. Status dihitung otomatis dari tanggal.

    `status` dan `status_label` sama persis dengan `siwak.TimelineEvent`:
    keduanya yang dibaca `components/timeline.html`.
    """

    judul = models.CharField(max_length=200, verbose_name="Judul")
    deskripsi = models.TextField(blank=True)
    tanggal_mulai = models.DateField(verbose_name="Tanggal Mulai")
    tanggal_selesai = models.DateField(
        null=True, blank=True,
        help_text="Kosongkan jika tahapan hanya berlangsung 1 hari.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Timeline AM-FM"
        verbose_name_plural = "Timeline AM-FM"
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


def bukti_path(instance, filename):
    # Tidak menyertakan nama/NPM dalam URL storage.
    return f"amfm/pendaftaran/{uuid.uuid4().hex}.{filename.rsplit('.', 1)[-1].lower()}"


def bukti_storage():
    if settings.AWS_STORAGE_BUCKET_NAME and not settings.RUNNING_TESTS:
        from storages.backends.s3 import S3Storage
        return S3Storage(default_acl="private", querystring_auth=True, custom_domain=None)
    return default_storage


class Pendaftaran(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    npm = models.CharField(max_length=20, unique=True, editable=False)
    nama_lengkap = models.CharField(max_length=200, editable=False)
    jurusan = models.CharField(max_length=10, editable=False)
    jenis_kelamin = models.CharField(max_length=1, choices=[("L", "Laki-laki"), ("P", "Perempuan")])
    kontak = models.CharField(max_length=100, verbose_name="Nomor WhatsApp atau ID Line")
    bukti_follow = models.ImageField(upload_to=bukti_path, storage=bukti_storage, blank=True)
    bukti_follow_2 = models.ImageField(upload_to=bukti_path, storage=bukti_storage, blank=True)
    pilihan_1 = models.ForeignKey("birdep.BirDep", on_delete=models.PROTECT, related_name="pendaftar_pilihan_1")
    pilihan_2 = models.ForeignKey("birdep.BirDep", on_delete=models.PROTECT, related_name="pendaftar_pilihan_2")
    motivasi = models.TextField(max_length=50)
    portofolio = models.URLField(blank=True)
    status = models.CharField(max_length=10, default="menunggu", choices=[
        ("menunggu", "Menunggu"), ("diterima", "Diterima"), ("ditolak", "Ditolak"),
    ])
    penempatan = models.ForeignKey("birdep.BirDep", on_delete=models.PROTECT, null=True, blank=True, related_name="anggota_amfm")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pendaftaran AM-FM"
        verbose_name_plural = "Pendaftaran AM-FM"
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(
            condition=~models.Q(pilihan_1=models.F("pilihan_2")), name="amfm_pilihan_berbeda",
        )]

    def __str__(self):
        return f"{self.nama_lengkap} ({self.npm})"
