from django.contrib import admin
from .models import Kegiatan

# Register your models here.


class KegiatanAdmin(admin.ModelAdmin):
    list_display = ("judul", "kategori", "tanggal", "lokasi")
    list_filter = ("kategori", "tanggal")
    search_fields = ("judul", "deskripsi", "lokasi")

admin.site.register(Kegiatan, KegiatanAdmin)