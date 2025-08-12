from django.db import models
from django.urls import reverse
from django.utils.text import slugify

class BirDep(models.Model):
    nama = models.CharField(max_length=200, verbose_name="Nama BirDep")
    slug = models.SlugField(unique=True, blank=True)
    logo_filename = models.CharField(max_length=100, verbose_name="Nama File Logo")
    tentang_deskripsi = models.TextField(verbose_name="Deskripsi Tentang", blank=True)
    tugas = models.TextField(verbose_name="Tugas", blank=True)
    tanggung_jawab = models.TextField(verbose_name="Tanggung Jawab", blank=True)
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat pada")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Diperbarui pada")
    
    class Meta:
        verbose_name = "BirDep"
        verbose_name_plural = "BirDeps"
        ordering = ['nama']
    
    def __str__(self):
        return self.nama
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nama)
        super().save(*args, **kwargs)
    
    def get_absolute_url(self):
        return reverse('main:birdep_tentang', kwargs={'slug': self.slug})
    
    @property
    def logo_url(self):
        """Helper method untuk mendapatkan URL logo"""
        if self.logo_filename:
            return f'images/{self.logo_filename}'
        return 'images/default-logo.png' 

class Program(models.Model):
    birdep = models.ForeignKey(BirDep, on_delete=models.CASCADE, related_name='programs')
    judul = models.CharField(max_length=200, verbose_name="Judul Program")
    deskripsi = models.TextField(verbose_name="Deskripsi Program")
    urutan = models.IntegerField(default=0, verbose_name="Urutan Tampilan")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat pada")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Diperbarui pada")
    
    class Meta:
        verbose_name = "Program"
        verbose_name_plural = "Programs"
        ordering = ['urutan', 'judul']
    
    def __str__(self):
        return f"{self.birdep.nama} - {self.judul}"

class Fungsionaris(models.Model):
    birdep = models.ForeignKey(BirDep, on_delete=models.CASCADE, related_name='fungsionaris_set')
    nama = models.CharField(max_length=200, verbose_name="Nama Lengkap")
    jabatan = models.CharField(max_length=100, verbose_name="Jabatan")
    foto = models.ImageField(upload_to='fungsionaris_photos/', blank=True, null=True, verbose_name="Foto Fungsionaris")
    urutan = models.IntegerField(default=0, verbose_name="Urutan Tampilan")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat pada")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Diperbarui pada")
    
    class Meta:
        verbose_name = "Fungsionaris"
        verbose_name_plural = "Fungsionaris"
        ordering = ['urutan', 'nama']
    
    def __str__(self):
        return f"{self.nama} - {self.jabatan} ({self.birdep.nama})"
