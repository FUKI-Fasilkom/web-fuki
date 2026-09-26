from django.contrib import admin
from .models import Fungsionaris


@admin.register(Fungsionaris)
class FungsionarisAdmin(admin.ModelAdmin):
    list_display = ('nama', 'jabatan')
