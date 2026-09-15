"""Konten beranda yang dikelola lewat Django admin.

Sebelum redesign 2026 beranda seluruhnya hardcode di template. Model-model di
sini memindahkan tiap section ke admin supaya pengurus bisa memperbarui isinya
tanpa menyentuh kode.
"""

from django.db import models


class TentangFuki(models.Model):
    """Section 'Apa Itu Fuki' — singleton, mengikuti pola siwak.SiwakInfo."""

    judul = models.CharField(max_length=200, default="Apa Itu Fuki?", verbose_name="Judul Section")
    deskripsi = models.TextField(blank=True, verbose_name="Deskripsi")

    class Meta:
        verbose_name = "Tentang FUKI (Beranda)"
        verbose_name_plural = "Tentang FUKI (Beranda)"

    def __str__(self):
        return self.judul

    def save(self, *args, **kwargs):
        # Singleton: selalu pakai pk=1 supaya admin tidak bisa membuat > 1 baris.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class TentangFukiGambar(models.Model):
    """Satu ubin pada mosaik gambar section 'Apa Itu Fuki' (desain memakai 5)."""

    tentang = models.ForeignKey(
        TentangFuki, on_delete=models.CASCADE, related_name="gambar_set"
    )
    gambar = models.ImageField(upload_to="tentang_fuki/", verbose_name="Gambar")
    alt = models.CharField(
        max_length=200, blank=True,
        verbose_name="Teks Alternatif",
        help_text="Deskripsi singkat gambar untuk pembaca layar dan SEO.",
    )
    urutan = models.PositiveIntegerField(default=0, verbose_name="Urutan Tampil")

    class Meta:
        ordering = ["urutan", "id"]
        verbose_name = "Gambar Tentang FUKI"
        verbose_name_plural = "Gambar Tentang FUKI"

    def __str__(self):
        return self.alt or f"Gambar #{self.pk}"


class Activity(models.Model):
    """Section 'Our Activity' — kartu dokumentasi yang di-scroll horizontal."""

    judul = models.CharField(max_length=200, verbose_name="Judul Kegiatan")
    gambar = models.ImageField(upload_to="activity/", blank=True, null=True, verbose_name="Gambar")
    deskripsi = models.TextField(blank=True, verbose_name="Deskripsi")
    urutan = models.PositiveIntegerField(default=0, verbose_name="Urutan Tampil")
    is_active = models.BooleanField(default=True, verbose_name="Tampilkan")

    class Meta:
        ordering = ["urutan", "judul"]
        verbose_name = "Activity (Beranda)"
        verbose_name_plural = "Activity (Beranda)"

    def __str__(self):
        return self.judul


class Podcast(models.Model):
    """Section 'Listen to Our Podcast'."""

    judul = models.CharField(max_length=200, verbose_name="Judul Episode")
    deskripsi = models.TextField(blank=True, verbose_name="Deskripsi")
    thumbnail = models.ImageField(upload_to="podcast/", blank=True, null=True, verbose_name="Thumbnail")
    link = models.URLField(
        max_length=500, blank=True,
        verbose_name="Link Episode",
        help_text="Tautan Spotify/YouTube untuk tombol 'Dengarkan Sekarang'.",
    )
    urutan = models.PositiveIntegerField(default=0, verbose_name="Urutan Tampil")
    is_active = models.BooleanField(default=True, verbose_name="Tampilkan")

    class Meta:
        ordering = ["urutan", "judul"]
        verbose_name = "Podcast (Beranda)"
        verbose_name_plural = "Podcast (Beranda)"

    def __str__(self):
        return self.judul


class CompanyProfile(models.Model):
    """Section 'Company Profile' — kartu video profil organisasi."""

    judul = models.CharField(max_length=200, verbose_name="Judul")
    deskripsi = models.TextField(blank=True, verbose_name="Deskripsi")
    thumbnail = models.ImageField(
        upload_to="company_profile/", blank=True, null=True, verbose_name="Thumbnail"
    )
    link = models.URLField(max_length=500, blank=True, verbose_name="Link Video")
    urutan = models.PositiveIntegerField(default=0, verbose_name="Urutan Tampil")
    is_active = models.BooleanField(default=True, verbose_name="Tampilkan")

    class Meta:
        ordering = ["urutan", "judul"]
        verbose_name = "Company Profile (Beranda)"
        verbose_name_plural = "Company Profile (Beranda)"

    def __str__(self):
        return self.judul
