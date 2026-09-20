import csv
import zipfile
from io import BytesIO

from django.contrib import admin
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import format_html
from django.utils.text import slugify

from .models import (
    Answer,
    AssessmentAspect,
    AssignmentReview,
    AssignmentReviewHistory,
    Choice,
    EventRSVP,
    FAQMentoring,
    GaleriFoto,
    KelompokMentoring,
    KetuaSiwak,
    MahasiswaProfile,
    MenteeAssessment,
    MentorFeedback,
    MentoringAttendance,
    MentoringBenefit,
    MentoringSession,
    MentoringTujuan,
    Question,
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
    list_display = ["judul", "tanggal", "lokasi", "rsvp_dibuka", "urutan"]
    list_editable = ["urutan"]
    list_filter = ["rsvp_dibuka", "tanggal"]
    search_fields = ["judul", "deskripsi", "lokasi"]


@admin.register(TimelineEvent)
class TimelineEventAdmin(admin.ModelAdmin):
    list_display = ["judul", "kategori", "tanggal_mulai", "tanggal_selesai", "status_label", "is_active"]
    list_filter = ["kategori", "is_active"]
    search_fields = ["judul", "deskripsi"]
    date_hierarchy = "tanggal_mulai"


@admin.register(KelompokMentoring)
class KelompokMentoringAdmin(admin.ModelAdmin):
    list_display = ["nama_kelompok", "mentor_names", "jumlah_peserta", "kapasitas", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["nama_kelompok"]

    def mentor_names(self, obj):
        return ", ".join(m.nama_lengkap for m in obj.daftar_mentor) or "-"
    mentor_names.short_description = "Mentor"

    def jumlah_peserta(self, obj):
        return obj.daftar_mentee.count()
    jumlah_peserta.short_description = "Jumlah Peserta"


@admin.register(MentoringSession)
class MentoringSessionAdmin(admin.ModelAdmin):
    list_display = ["kelompok", "nomor", "tanggal", "is_active"]
    list_display_links = ["kelompok", "nomor"]
    list_editable = ["tanggal", "is_active"]
    list_filter = ["nomor", "is_active"]
    search_fields = ["kelompok__nama_kelompok"]
    ordering = ["kelompok__nama_kelompok", "nomor"]
    actions = ["activate_sessions", "deactivate_sessions"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Aktifkan sesi terpilih")
    def activate_sessions(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="Nonaktifkan sesi terpilih")
    def deactivate_sessions(self, request, queryset):
        queryset.update(is_active=False)


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


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    fields = ["urutan", "tipe", "pertanyaan"]
    ordering = ["urutan"]


class TugasSubmissionInline(admin.TabularInline):
    model = TugasSubmission
    extra = 0
    readonly_fields = ["user", "status", "submitted_at"]
    can_delete = False


@admin.register(Tugas)
class TugasAdmin(admin.ModelAdmin):
    list_display = ["judul_tugas", "deadline", "is_active", "jumlah_pertanyaan", "jumlah_submission"]
    list_filter = ["is_active"]
    search_fields = ["judul_tugas", "deskripsi"]
    inlines = [QuestionInline, TugasSubmissionInline]
    actions = ["download_all_submissions"]

    def jumlah_submission(self, obj):
        return obj.submissions.count()
    jumlah_submission.short_description = "Submission"

    def jumlah_pertanyaan(self, obj):
        return obj.questions.count()
    jumlah_pertanyaan.short_description = "Pertanyaan"

    @admin.action(description="Download seluruh submission (ZIP)")
    def download_all_submissions(self, request, queryset):
        """PRD 5.1 Admin Features: 'Download seluruh submission.'"""
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            for tugas in queryset:
                for sub in tugas.submissions.select_related("user"):
                    if not sub.file:
                        continue
                    folder = f"{tugas.pk}-{slugify(tugas.judul_tugas) or 'tugas'}"
                    arcname = f"{folder}/{sub.pk}_{sub.file.name.split('/')[-1]}"
                    with sub.file.open("rb") as fh:
                        zf.writestr(arcname, fh.read())
        buffer.seek(0)
        response = HttpResponse(buffer.read(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="submission_tugas.zip"'
        return response


@admin.register(MahasiswaProfile)
class MahasiswaProfileAdmin(admin.ModelAdmin):
    """Satu-satunya tempat mentee dan mentor. Untuk pengelolaan sehari-hari pakai
    panel SIWAK di /siwak/admin/data/peserta/ dan /siwak/admin/data/mentor/,
    yang punya dropdown kelompok langsung di daftarnya; halaman ini cadangan
    teknis dan sumber autocomplete untuk presensi, penilaian, dan feedback."""

    list_display = ["nama_lengkap", "npm", "role", "kelompok", "jurusan", "angkatan", "user"]
    search_fields = ["nama_lengkap", "npm"]
    list_filter = ["role", "jurusan", "angkatan", "kelompok"]
    autocomplete_fields = ["kelompok"]
    list_select_related = ["kelompok", "user"]


@admin.register(EventRSVP)
class EventRSVPAdmin(admin.ModelAdmin):
    list_display = ["user", "event", "status_kehadiran", "status_kupon", "created_at"]
    list_filter = ["event", "status_kehadiran", "status_kupon"]
    search_fields = ["user__username", "user__mahasiswa_profile__nama_lengkap"]
    actions = ["export_attendance_csv"]

    @admin.action(description="Export attendance (CSV)")
    def export_attendance_csv(self, request, queryset):
        """PRD 8 Admin Capabilities: 'Export attendance.'"""
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="attendance_siwak.csv"'
        writer = csv.writer(response)
        writer.writerow(["Nama", "NPM", "Event", "Status Kehadiran", "Check-in", "Status Kupon", "Redeemed"])
        for rsvp in queryset.select_related("user__mahasiswa_profile", "event"):
            profile = getattr(rsvp.user, "mahasiswa_profile", None)
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


# ---------------------------------------------------------------------------
# Model mentor (presensi, penilaian, feedback) & isi tugas.
# Semuanya sengaja didaftarkan lengkap supaya setiap relasi bisa diuji langsung
# dari halaman admin, bukan hanya lewat panel SIWAK di /siwak/admin/.
# ---------------------------------------------------------------------------


@admin.register(MentoringAttendance)
class MentoringAttendanceAdmin(admin.ModelAdmin):
    list_display = ["peserta", "session", "kelompok", "status", "recorded_by", "updated_at"]
    list_filter = ["status", "session__nomor", "session__kelompok"]
    search_fields = [
        "peserta__nama_lengkap",
        "peserta__npm",
        "session__kelompok__nama_kelompok",
    ]
    autocomplete_fields = ["session", "peserta", "recorded_by"]
    list_select_related = ["peserta", "session__kelompok", "recorded_by"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Kelompok", ordering="session__kelompok__nama_kelompok")
    def kelompok(self, obj):
        return obj.session.kelompok


@admin.register(AssessmentAspect)
class AssessmentAspectAdmin(admin.ModelAdmin):
    list_display = ["nama", "urutan", "is_active"]
    list_editable = ["urutan", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["nama"]


@admin.register(MenteeAssessment)
class MenteeAssessmentAdmin(admin.ModelAdmin):
    list_display = ["peserta", "kelompok", "aspect", "score", "assessed_by", "updated_at"]
    list_filter = ["aspect", "peserta__kelompok"]
    search_fields = [
        "peserta__nama_lengkap",
        "peserta__npm",
        "aspect__nama",
    ]
    autocomplete_fields = ["peserta", "aspect", "assessed_by"]
    list_select_related = ["peserta", "peserta__kelompok", "aspect", "assessed_by"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Kelompok", ordering="peserta__kelompok__nama_kelompok")
    def kelompok(self, obj):
        return obj.peserta.kelompok


@admin.register(MentorFeedback)
class MentorFeedbackAdmin(admin.ModelAdmin):
    list_display = ["peserta", "session", "mentor", "ringkasan", "created_at"]
    list_filter = ["session__nomor", "session__kelompok", "mentor"]
    search_fields = [
        "peserta__nama_lengkap",
        "peserta__npm",
        "isi",
    ]
    autocomplete_fields = ["session", "peserta", "mentor"]
    list_select_related = ["peserta", "session__kelompok", "mentor"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Feedback")
    def ringkasan(self, obj):
        return obj.isi[:60] + ("..." if len(obj.isi) > 60 else "")


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 0
    fields = ["urutan", "teks"]
    ordering = ["urutan"]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["pertanyaan_singkat", "tugas", "tipe", "urutan", "jumlah_pilihan"]
    list_editable = ["urutan"]
    list_filter = ["tipe", "tugas"]
    search_fields = ["pertanyaan", "tugas__judul_tugas"]
    autocomplete_fields = ["tugas"]
    list_select_related = ["tugas"]
    inlines = [ChoiceInline]

    @admin.display(description="Pertanyaan", ordering="pertanyaan")
    def pertanyaan_singkat(self, obj):
        return obj.pertanyaan[:80]

    @admin.display(description="Pilihan")
    def jumlah_pilihan(self, obj):
        return obj.choices.count()


@admin.register(Choice)
class ChoiceAdmin(admin.ModelAdmin):
    list_display = ["teks", "question", "urutan"]
    list_editable = ["urutan"]
    list_filter = ["question__tugas"]
    search_fields = ["teks", "question__pertanyaan"]
    autocomplete_fields = ["question"]
    list_select_related = ["question__tugas"]


class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 0
    autocomplete_fields = ["question", "selected_choice"]


class AssignmentReviewInline(admin.StackedInline):
    model = AssignmentReview
    extra = 0
    autocomplete_fields = ["reviewer"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(TugasSubmission)
class TugasSubmissionAdmin(admin.ModelAdmin):
    """Standalone selain inline di TugasAdmin, supaya relasi Answer &
    AssignmentReview bisa ditelusuri dari satu submission."""

    list_display = ["tugas", "user", "status", "berkas_tugas", "nilai", "jumlah_jawaban", "submitted_at"]
    list_filter = ["status", "tugas"]
    search_fields = ["tugas__judul_tugas", "user__username", "user__mahasiswa_profile__nama_lengkap"]
    autocomplete_fields = ["tugas"]
    list_select_related = ["tugas", "user"]
    readonly_fields = ["status", "submitted_at"]
    inlines = [AnswerInline, AssignmentReviewInline]

    @admin.display(description="Berkas tugas")
    def berkas_tugas(self, obj):
        if not obj.file:
            return "-"
        return format_html('<a href="{}">Unduh berkas</a>', reverse("siwak:submission_download", args=[obj.pk]))

    @admin.display(description="Nilai")
    def nilai(self, obj):
        review = getattr(obj, "mentor_review", None)
        return review.score if review else "-"

    @admin.display(description="Jawaban")
    def jumlah_jawaban(self, obj):
        return obj.answers.count()


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ["submission", "question", "isi_singkat"]
    list_filter = ["question__tugas", "question__tipe"]
    search_fields = [
        "text_answer",
        "question__pertanyaan",
        "submission__user__username",
    ]
    autocomplete_fields = ["submission", "question", "selected_choice"]
    list_select_related = ["submission__tugas", "submission__user", "question"]

    @admin.display(description="Jawaban")
    def isi_singkat(self, obj):
        if obj.selected_choice:
            return obj.selected_choice.teks
        if obj.file_answer:
            return obj.file_answer.name.split("/")[-1]
        return obj.text_answer[:60]


@admin.register(AssignmentReview)
class AssignmentReviewAdmin(admin.ModelAdmin):
    list_display = ["submission", "score", "reviewer", "updated_at"]
    list_filter = ["submission__tugas", "reviewer"]
    search_fields = [
        "submission__user__username",
        "submission__tugas__judul_tugas",
        "feedback",
    ]
    autocomplete_fields = ["submission", "reviewer"]
    list_select_related = ["submission__tugas", "submission__user", "reviewer"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(AssignmentReviewHistory)
class AssignmentReviewHistoryAdmin(admin.ModelAdmin):
    """Append-only: cuma untuk dibaca, jangan diedit lewat admin."""

    list_display = ["submission", "score", "reviewer", "created_at"]
    list_filter = ["submission__tugas", "reviewer"]
    search_fields = [
        "submission__user__username",
        "submission__tugas__judul_tugas",
        "feedback",
    ]
    list_select_related = ["submission__tugas", "submission__user", "reviewer"]
    readonly_fields = ["submission", "score", "feedback", "reviewer", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
