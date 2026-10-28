"""Form pengelola menggunakan widget design system panel bersama."""
from django import forms
from django.core.exceptions import ValidationError

from main.panel import CENTANG, ISIAN, PILIHAN, PanelForm
from birdep.models import BirDep
from .models import AmfmBenefit, AmfmInfo, AmfmTimeline, Pendaftaran
from .services.seleksi import STATUS, validasi_keputusan


class KeputusanForm(PanelForm):
    class Meta:
        model = Pendaftaran
        fields = ["status", "penempatan"]
        labels = {"status": "Status Penerimaan", "penempatan": "Penempatan Birdept"}
        widgets = {"status": forms.RadioSelect()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [(value, STATUS[value]) for value in ("diterima", "menunggu", "ditolak")]
        self.fields["penempatan"].queryset = self.fields["penempatan"].queryset.filter(
            pk__in=[self.instance.pilihan_1_id, self.instance.pilihan_2_id],
        )
        self.fields["penempatan"].empty_label = "— Belum ditempatkan —"

    def clean(self):
        data = super().clean()
        if data.get("status"):
            try:
                penempatan_id = validasi_keputusan(
                    self.instance, data["status"], getattr(data.get("penempatan"), "pk", None),
                )
                if penempatan_id is None:
                    data["penempatan"] = None
            except ValidationError as error:
                self.add_error("penempatan", error)
        return data


class StatusMassalForm(forms.Form):
    ids = forms.ModelMultipleChoiceField(queryset=Pendaftaran.objects.all())
    status = forms.ChoiceField(label="Status baru", choices=[("", "Pilih status"), *STATUS.items()], widget=forms.Select(attrs={"class": PILIHAN}))
    konfirmasi = forms.BooleanField(widget=forms.CheckboxInput(attrs={"class": CENTANG}))
    penempatan = forms.ModelChoiceField(
        label="Penempatan untuk status Diterima", queryset=BirDep.objects.all(), required=False,
        empty_label="Pertahankan penempatan", widget=forms.Select(attrs={"class": PILIHAN}),
    )


class PengaturanForm(PanelForm):
    class Meta:
        model = AmfmInfo
        fields = ["guidebook_url", "kurikulum_url", "status_pendaftaran", "dibuka_pada", "ditutup_pada"]
        labels = {"status_pendaftaran": "Status pendaftaran", "dibuka_pada": "Waktu pembukaan (WIB)", "ditutup_pada": "Deadline (WIB)"}


class KontenForm(PanelForm):
    class Meta:
        model = AmfmInfo
        fields = ["hero_judul", "hero_tagline", "hero_deskripsi", "apa_itu_deskripsi", "apa_itu_gambar", "tujuan", "cta_deskripsi"]


class BenefitForm(PanelForm):
    class Meta:
        model = AmfmBenefit
        fields = ["judul", "deskripsi", "urutan"]


class TimelineForm(PanelForm):
    class Meta:
        model = AmfmTimeline
        fields = ["judul", "deskripsi", "tanggal_mulai", "tanggal_selesai", "is_active"]

    def clean(self):
        data = super().clean()
        if data.get("tanggal_mulai") and data.get("tanggal_selesai") and data["tanggal_selesai"] < data["tanggal_mulai"]:
            self.add_error("tanggal_selesai", "Tanggal selesai tidak boleh sebelum tanggal mulai.")
        return data


class FilterPendaftarForm(forms.Form):
    q = forms.CharField(
        label="Cari nama atau NPM", required=False,
        widget=forms.SearchInput(attrs={"class": ISIAN, "placeholder": "Cari nama atau NPM"}),
    )
    birdept = forms.ModelChoiceField(
        label="Birdept", queryset=BirDep.objects.all(), required=False,
        empty_label="Semua Birdept", widget=forms.Select(attrs={"class": PILIHAN}),
    )
    status = forms.ChoiceField(
        label="Status", required=False, choices=[("", "Semua Status"), *STATUS.items()],
        widget=forms.Select(attrs={"class": PILIHAN}),
    )
