from django.contrib import admin

from .models import Activity, CompanyProfile, Podcast, TentangFuki, TentangFukiGambar


class TentangFukiGambarInline(admin.TabularInline):
    model = TentangFukiGambar
    extra = 1
    fields = ['gambar', 'alt', 'urutan']


@admin.register(TentangFuki)
class TentangFukiAdmin(admin.ModelAdmin):
    list_display = ['judul']
    inlines = [TentangFukiGambarInline]

    def has_add_permission(self, request):
        # Singleton: cukup satu baris, sunting yang sudah ada.
        return not TentangFuki.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ['judul', 'urutan', 'is_active']
    list_filter = ['is_active']
    search_fields = ['judul', 'deskripsi']
    list_editable = ['urutan', 'is_active']


@admin.register(Podcast)
class PodcastAdmin(admin.ModelAdmin):
    list_display = ['judul', 'link', 'urutan', 'is_active']
    list_filter = ['is_active']
    search_fields = ['judul', 'deskripsi']
    list_editable = ['urutan', 'is_active']


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ['judul', 'link', 'urutan', 'is_active']
    list_filter = ['is_active']
    search_fields = ['judul', 'deskripsi']
    list_editable = ['urutan', 'is_active']
