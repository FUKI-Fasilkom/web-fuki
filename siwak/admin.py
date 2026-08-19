import csv
import zipfile
from io import BytesIO

from django.contrib import admin
from django.http import HttpResponse

from .models import (
    EventRSVP,
    FAQMentoring,
    GaleriFoto,
    KelompokMentoring,
    KetuaSiwak,
    MabaProfile,
    Mentor,
    MentoringBenefit,
    MentoringTujuan,
    PesertaMentoring,
    SistemMentoring,
    SiwakEvent,
    SiwakInfo,
    TimelineEvent,
    Tugas,
    TugasSubmission,
)


@admin.register(SiwakInfo)
class SiwakInfoAdmin(admin.ModelAdmin):
    """Singleton: PRD 4.1 konten halaman utama SIWAK-NG."""

    list_display = ["__str__", "updated_at"]

    def has_add_permission(self, request):
        return not SiwakInfo.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SiwakEvent)
class SiwakEventAdmin(admin.ModelAdmin):
    list_display = ["judul", "tipe", "tanggal", "rsvp_dibuka", "urutan"]
    list_editable = ["rsvp_dibuka", "urutan"]
    list_filter = ["tipe", "rsvp_dibuka"]


@admin.register(TimelineEvent)
class TimelineEventAdmin(admin.ModelAdmin):
    list_display = ["judul", "kategori", "tanggal_mulai", "tanggal_selesai", "status_label", "is_active"]
    list_filter = ["kategori", "is_active"]
    search_fields = ["judul", "deskripsi"]
    date_hierarchy = "tanggal_mulai"


@admin.register(Mentor)
class MentorAdmin(admin.ModelAdmin):
    list_display = ["nama"]
    search_fields = ["nama"]


@admin.register(KelompokMentoring)
class KelompokMentoringAdmin(admin.ModelAdmin):
    list_display = ["nama_kelompok", "mentor_names", "jumlah_peserta", "kapasitas", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["nama_kelompok"]
    filter_horizontal = ["mentors"]

    def mentor_names(self, obj):
        return ", ".join(m.nama for m in obj.mentors.all()) or "-"
    mentor_names.short_description = "Mentor"

    def jumlah_peserta(self, obj):
        return obj.peserta_list.count()
    jumlah_peserta.short_description = "Jumlah Peserta"


@admin.register(PesertaMentoring)
class PesertaMentoringAdmin(admin.ModelAdmin):
    """PRD 4.3: 'Admin dapat upload data kelompok.' Gunakan Import via list ini,
    atau tambah satu-satu; untuk upload massal pakai Excel -> copy-paste tetap
    lebih aman lewat halaman 'Add' berulang / manajemen command loaddata."""

    list_display = ["nama_lengkap", "jurusan", "npm", "kelompok", "user"]
    list_filter = ["jurusan", "kelompok"]
    search_fields = ["nama_lengkap", "npm"]
    autocomplete_fields = ["kelompok"]


@admin.register(MentoringTujuan)
class MentoringTujuanAdmin(admin.ModelAdmin):
    list_display = ["judul", "urutan"]
    list_editable = ["urutan"]


@admin.register(MentoringBenefit)
class MentoringBenefitAdmin(admin.ModelAdmin):
    list_display = ["judul", "urutan"]
    list_editable = ["urutan"]


@admin.register(SistemMentoring)
class SistemMentoringAdmin(admin.ModelAdmin):
    list_display = ["__str__", "urutan"]
    list_editable = ["urutan"]


@admin.register(GaleriFoto)
class GaleriFotoAdmin(admin.ModelAdmin):
    list_display = ["caption", "urutan"]
    list_editable = ["urutan"]


@admin.register(KetuaSiwak)
class KetuaSiwakAdmin(admin.ModelAdmin):
    list_display = ["nama", "tahun", "urutan"]
    list_editable = ["urutan"]


@admin.register(FAQMentoring)
class FAQMentoringAdmin(admin.ModelAdmin):
    list_display = ["pertanyaan", "urutan"]
    list_editable = ["urutan"]


class TugasSubmissionInline(admin.TabularInline):
    model = TugasSubmission
    extra = 0
    readonly_fields = ["user", "status", "submitted_at"]
    can_delete = False


@admin.register(Tugas)
class TugasAdmin(admin.ModelAdmin):
    list_display = ["judul_tugas", "deadline", "is_active", "jumlah_submission"]
    list_filter = ["is_active"]
    inlines = [TugasSubmissionInline]
    actions = ["download_all_submissions"]

    def jumlah_submission(self, obj):
        return obj.submissions.count()
    jumlah_submission.short_description = "Submission"

    @admin.action(description="Download seluruh submission (ZIP)")
    def download_all_submissions(self, request, queryset):
        """PRD 5.1 Admin Features: 'Download seluruh submission.'"""
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            for tugas in queryset:
                for sub in tugas.submissions.select_related("user"):
                    if not sub.file:
                        continue
                    arcname = f"{tugas.judul_tugas}/{sub.user.username}_{sub.file.name.split('/')[-1]}"
                    with sub.file.open("rb") as fh:
                        zf.writestr(arcname, fh.read())
        buffer.seek(0)
        response = HttpResponse(buffer.read(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="submission_tugas.zip"'
        return response


@admin.register(MabaProfile)
class MabaProfileAdmin(admin.ModelAdmin):
    list_display = ["nama_lengkap", "npm", "jurusan", "angkatan"]
    search_fields = ["nama_lengkap", "npm"]
    list_filter = ["jurusan", "angkatan"]


@admin.register(EventRSVP)
class EventRSVPAdmin(admin.ModelAdmin):
    list_display = ["user", "event", "status_kehadiran", "status_kupon", "created_at"]
    list_filter = ["event", "status_kehadiran", "status_kupon"]
    search_fields = ["user__username", "user__maba_profile__nama_lengkap"]
    actions = ["export_attendance_csv"]

    @admin.action(description="Export attendance (CSV)")
    def export_attendance_csv(self, request, queryset):
        """PRD 8 Admin Capabilities: 'Export attendance.'"""
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="attendance_siwak.csv"'
        writer = csv.writer(response)
        writer.writerow(["Nama", "NPM", "Event", "Status Kehadiran", "Check-in", "Status Kupon", "Redeemed"])
        for rsvp in queryset.select_related("user__maba_profile", "event"):
            profile = getattr(rsvp.user, "maba_profile", None)
            writer.writerow([
                profile.nama_lengkap if profile else rsvp.user.username,
                profile.npm if profile else "",
                rsvp.event.judul,
                rsvp.status_kehadiran,
                rsvp.checked_in_at or "",
                rsvp.status_kupon,
                rsvp.redeemed_at or "",
            ])
        return response