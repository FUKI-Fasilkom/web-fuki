from django.db import models

# Create your models here.

class Fungsionaris(models.Model):
    nama = models.CharField(max_length=100)
    jabatan = models.CharField(max_length=150)
    foto = models.ImageField(upload_to='fungsionaris/')

    def __str__(self):
        return f"{self.nama} - {self.jabatan}"
