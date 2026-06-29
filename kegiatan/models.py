from django.db import models

# Create your models here.
class Kegiatan(models.Model):
    judul = models.CharField(max_length=200, verbose_name="Judul Kegiatan")
    deskripsi = models.TextField(verbose_name="Deskripsi Kegiatan", blank=True)

    # waktu dan tempat
    tanggal = models.DateField(verbose_name="Tanggal Kegiatan")
    start_time = models.TimeField(null=True,verbose_name="Jam Mulai")
    end_time = models.TimeField(null=True, verbose_name="Jam Selesai")

    lokasi = models.CharField(max_length=200, verbose_name="Lokasi Kegiatan")
    link_lokasi = models.CharField(verbose_name="Link lokasi kegiatan", null=True, blank=True)

    guest_star = models.CharField(verbose_name="Guest Star Kegiatan", null=True)
    contact = models.CharField(verbose_name="Contact Kegiatan", null=True)
    link_registrasi = models.CharField(verbose_name="Link pendaftaran kegiatan", null=True, blank=True)

    def __str__(self):
        return self.judul