from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html

from .models import AmfmBenefit, AmfmInfo, AmfmTimeline, Pendaftaran
from .panel_forms import KeputusanForm
from .services.seleksi import simpan_keputusan, ubah_status_massal


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


@admin.register(Pendaftaran)
class PendaftaranAdmin(admin.ModelAdmin):
    form = KeputusanForm
    list_display = ["nama_lengkap", "npm", "pilihan_1", "pilihan_2", "status", "penempatan", "created_at"]
    list_filter = ["status", "pilihan_1", "pilihan_2", "penempatan"]
    search_fields = ["nama_lengkap", "npm"]
    list_select_related = ["pilihan_1", "pilihan_2", "penempatan"]
    exclude = ["bukti_follow"]
    readonly_fields = ["user", "npm", "nama_lengkap", "jurusan", "jenis_kelamin", "kontak",
                       "bukti_terlindungi", "pilihan_1", "pilihan_2", "motivasi", "portofolio", "created_at"]
    actions = ["terima", "tolak", "tunggu"]

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        simpan_keputusan(obj.pk, obj.status, obj.penempatan_id)

    def get_urls(self):
        return [path("<int:pk>/bukti/", self.admin_site.admin_view(self.unduh_bukti),
                     name="amfm_pendaftaran_bukti")] + super().get_urls()

    @admin.display(description="Bukti follow Instagram")
    def bukti_terlindungi(self, obj):
        return format_html('<a href="{}">Unduh bukti follow</a>', reverse("admin:amfm_pendaftaran_bukti", args=[obj.pk]))

    def unduh_bukti(self, request, pk):
        obj = get_object_or_404(Pendaftaran, pk=pk)
        if not self.has_view_or_change_permission(request, obj):
            raise PermissionDenied
        try:
            file = obj.bukti_follow.open("rb")
        except FileNotFoundError:
            raise Http404 from None
        response = FileResponse(file, as_attachment=True, filename="bukti-follow" + (".png" if obj.bukti_follow.name.endswith(".png") else ".jpg"))
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @admin.action(description="Tandai Diterima", permissions=["change"])
    def terima(self, request, queryset):
        self._status_massal(request, queryset, "diterima")

    @admin.action(description="Tandai Ditolak", permissions=["change"])
    def tolak(self, request, queryset):
        self._status_massal(request, queryset, "ditolak")

    @admin.action(description="Tandai Menunggu", permissions=["change"])
    def tunggu(self, request, queryset):
        self._status_massal(request, queryset, "menunggu")

    def _status_massal(self, request, queryset, status):
        try:
            jumlah = ubah_status_massal(queryset.values_list("pk", flat=True), status)
        except ValidationError as error:
            self.message_user(request, " ".join(error.messages), level=messages.ERROR)
        else:
            self.message_user(request, f"Status {jumlah} pendaftar berhasil diperbarui.")
