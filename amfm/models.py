"""Konten halaman Open Recruitment AM-FM (PRD 4.1).

Bentuknya sengaja meniru konten landing SIWAK (`SiwakInfo`, `MentoringBenefit`,
`TimelineEvent`): desain halamannya memakai kartu benefit dan timeline yang sama,
dan keduanya dirender oleh komponen bersama di `templates/components/`.
"""

from django.db import models
from django.utils import timezone


class AmfmInfo(models.Model):
    """Konten singleton halaman AM-FM: hero, 'Apa itu', Tujuan, dan CTA.

    Pengaturan pendaftaran (buka/tutup, deadline, link guidebook & kurikulum)
    menyusul di sini bersama formulirnya.
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
