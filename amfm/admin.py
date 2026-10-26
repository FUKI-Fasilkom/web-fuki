from django.contrib import admin

from .models import AmfmBenefit, AmfmInfo, AmfmTimeline


@admin.register(AmfmInfo)
class AmfmInfoAdmin(admin.ModelAdmin):
    """Singleton: PRD 4.1 konten halaman AM-FM."""

    list_display = ["__str__", "updated_at"]

    def has_add_permission(self, request):
        return not AmfmInfo.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AmfmBenefit)
class AmfmBenefitAdmin(admin.ModelAdmin):
    list_display = ["judul", "urutan"]
    list_editable = ["urutan"]
    search_fields = ["judul", "deskripsi"]


@admin.register(AmfmTimeline)
class AmfmTimelineAdmin(admin.ModelAdmin):
    list_display = ["judul", "tanggal_mulai", "tanggal_selesai", "status_label", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["judul", "deskripsi"]
    date_hierarchy = "tanggal_mulai"
