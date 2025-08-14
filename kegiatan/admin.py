from django.contrib import admin
from .models import Kegiatan

# Register your models here.

@admin.register(Kegiatan)
class KegiatanAdmin(admin.ModelAdmin):
    list_display = ("judul", "tanggal", "lokasi")
    list_filter = ("tanggal", "lokasi")
    search_fields = ("judul", "deskripsi", "lokasi")
    ordering = ("-tanggal",)
    date_hierarchy = "tanggal"  
