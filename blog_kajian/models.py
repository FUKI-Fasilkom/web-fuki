from django.db import models

class Kajian(models.Model):
    judul = models.CharField(max_length=255)
    penceramah = models.CharField(max_length=255, help_text="Nama Ustaz/Pembicara")
    tanggal = models.DateField()
    
    # Menggunakan ImageField
    # Pastikan di settings.py sudah dikonfigurasi MEDIA_URL dan MEDIA_ROOT
    image = models.ImageField(upload_to='kajian/', null=True, blank=True)
    
    deskripsi = models.TextField(help_text="Isi lengkap artikel kajian")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-tanggal']
        verbose_name = "Kajian"
        verbose_name_plural = "Daftar Kajian"

    def __str__(self):
        return f"{self.judul} - {self.penceramah}"