from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Kajian

@admin.register(Kajian)
class KajianAdmin(admin.ModelAdmin):
    list_display = ('judul', 'penceramah', 'tanggal', 'created_at')
    search_fields = ('judul', 'penceramah', 'deskripsi')
    list_filter = ('tanggal',)
    list_per_page = 20