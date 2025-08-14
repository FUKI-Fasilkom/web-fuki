from django.db import models

# Create your models here.
class Kegiatan(models.Model):
    judul = models.CharField(max_length=200, verbose_name="Judul Kegiatan")
    deskripsi = models.TextField(verbose_name="Deskripsi Kegiatan", blank=True)
    tanggal = models.DateTimeField(verbose_name="Tanggal Kegiatan")
    lokasi = models.CharField(max_length=200, verbose_name="Lokasi Kegiatan")

    def __str__(self):
        return self.judul