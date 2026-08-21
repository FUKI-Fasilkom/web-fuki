from django.contrib import admin

from .models import (
    FAQMentoring,
    GaleriFoto,
    KelompokMentoring,
    KetuaSiwak,
    MentoringBenefit,
    MentoringTujuan,
    Mentor,
    PesertaMentoring,
    SistemMentoring,
    SiwakEvent,
    SiwakInfo,
    TimelineEvent,
)


@admin.register(SiwakInfo)
class SiwakInfoAdmin(admin.ModelAdmin):
    list_display = ["__str__", "updated_at"]

    def has_add_permission(self, request):
        return not SiwakInfo.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SiwakEvent)
class SiwakEventAdmin(admin.ModelAdmin):
    list_display = ["judul", "tipe", "tanggal", "urutan"]
    list_editable = ["urutan"]
    list_filter = ["tipe"]


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
    list_display = ["nama_lengkap", "jurusan", "npm", "kelompok"]
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