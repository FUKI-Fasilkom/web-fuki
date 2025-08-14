from django.contrib import admin
from .models import Fungsionaris

# Register your models here.

@admin.register(Fungsionaris)
class FungsionarisAdmin(admin.ModelAdmin):
    list_display = ('nama', 'jabatan')
