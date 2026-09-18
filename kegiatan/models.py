from django.db import models
from django.urls import reverse


# Create your models here.
class Kegiatan(models.Model):
    # Label harus sama persis dengan tab filter di beranda.
    KATEGORI_CHOICES = [
        ('maba', 'Kegiatan Maba'),
        ('kajian', 'Kajian & Syiar'),
        ('sosial', 'Sosial'),
        ('internal', 'Internal'),
    ]

    judul = models.CharField(max_length=200, verbose_name="Judul Kegiatan")
    deskripsi = models.TextField(verbose_name="Deskripsi Kegiatan", blank=True)
    kategori = models.CharField(
        max_length=20, choices=KATEGORI_CHOICES, default='kajian',
        verbose_name="Kategori Kegiatan",
    )
    gambar = models.ImageField(
        upload_to='kegiatan/', blank=True, null=True, verbose_name="Gambar Kegiatan"
    )

    # waktu dan tempat
    tanggal = models.DateField(verbose_name="Tanggal Kegiatan")
    start_time = models.TimeField(null=True,verbose_name="Jam Mulai")
    end_time = models.TimeField(null=True, verbose_name="Jam Selesai")

    lokasi = models.CharField(max_length=200, verbose_name="Lokasi Kegiatan")
    link_lokasi = models.CharField(verbose_name="Link lokasi kegiatan", null=True, blank=True)

    guest_star = models.CharField(verbose_name="Guest Star Kegiatan", null=True)
    contact = models.CharField(verbose_name="Contact Kegiatan", null=True)
    link_registrasi = models.CharField(verbose_name="Link pendaftaran kegiatan", null=True, blank=True)

    class Meta:
        ordering = ['tanggal']

    def __str__(self):
        return self.judul

    def get_absolute_url(self):
        return reverse('kegiatan:detail', kwargs={'id': self.pk})
