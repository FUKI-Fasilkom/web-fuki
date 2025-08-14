from django.db import models

# Create your models here.
class Kegiatan(models.Model):
    judul = models.CharField(max_length=200)
    deskripsi = models.TextField()
    tanggal = models.DateTimeField()
    lokasi = models.CharField(max_length=200)

    def __str__(self):
        return self.judul