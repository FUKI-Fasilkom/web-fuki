try:
    from django.db import models
except Exception:
    # Fallback for editor/type-checker environments where Django isn't available.
    # At runtime (in a Django project) the real django.db.models will be imported.
    from types import SimpleNamespace
    models = SimpleNamespace()
from django.urls import reverse
from django.utils.text import slugify

class BirDep(models.Model):
    nama = models.CharField(max_length=200, verbose_name="Nama Singkat BirDep")
    nama_panjang = models.CharField(max_length=300, verbose_name="Nama Panjang BirDep", blank=True)
    slug = models.SlugField(unique=True, blank=True)
    logo_filename = models.CharField(max_length=100, verbose_name="Nama File Logo")
    tentang_deskripsi = models.TextField(verbose_name="Deskripsi Tentang", blank=True)
    visi = models.TextField(verbose_name="Visi", blank=True, help_text="Visi dari BirDep")
    misi = models.TextField(verbose_name="Misi", blank=True, help_text="Misi dari BirDep")
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

class PengurusInti(models.Model):
    KATEGORI_CHOICES = [
        ('pi', 'Pengurus Inti'),
        ('ki', 'Kontrol Internal'),
        ('mdc', 'Muslim Development Center'),
    ]

    kategori = models.CharField(
        max_length=10,
        choices=KATEGORI_CHOICES,
        default='pi',
        verbose_name="Kategori",
        help_text="Menentukan halaman tempat pengurus ini ditampilkan",
    )
    nama = models.CharField(max_length=200, verbose_name="Nama Lengkap")
    jabatan = models.CharField(max_length=100, verbose_name="Jabatan")
    slug = models.SlugField(unique=True, blank=True, max_length=220)
    foto = models.ImageField(upload_to='pengurus_inti_photos/', blank=True, null=True, verbose_name="Foto")
    ikhtisar = models.TextField(blank=True, verbose_name="Ikhtisar", help_text="Ringkasan singkat tentang pengurus")
    deskripsi_kerja = models.TextField(blank=True, verbose_name="Deskripsi Kerja", help_text="Detail deskripsi kerja dan tanggung jawab")
    urutan = models.IntegerField(default=0, verbose_name="Urutan Tampilan")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat pada")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Diperbarui pada")
    
    class Meta:
        verbose_name = "Pengurus Inti"
        verbose_name_plural = "Pengurus Inti"
        ordering = ['kategori', 'urutan', 'nama']

    def __str__(self):
        return f"{self.nama} - {self.jabatan}"

    def save(self, *args, **kwargs):
        # Slug dibuat dari kategori + nama, bukan jabatan, karena jabatan bisa
        # berulang (mis. dua "Wakil Ketua KI") sedangkan slug harus unik.
        if not self.slug:
            self.slug = slugify(f"{self.kategori}-{self.nama}")
        super().save(*args, **kwargs)
    
    def get_absolute_url(self):
        return reverse('birdep:pi_detail', kwargs={'slug': self.slug})