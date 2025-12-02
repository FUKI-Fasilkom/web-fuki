from django.contrib import admin
from .models import Kegiatan

# Register your models here.


class KegiatanAdmin(admin.ModelAdmin):
    list_display = ("judul", "tanggal", "lokasi")

admin.site.register(Kegiatan, KegiatanAdmin)