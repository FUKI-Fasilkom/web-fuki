from django import forms
from django.core.exceptions import ValidationError

from .models import JURUSAN_CHOICES, EventRSVP, Tugas, TugasSubmission

INPUT_CLASSES = (
    "w-full rounded-xl border-[3px] border-[#3A3A3A] bg-[#EFEFEF] px-4 py-3 "
    "text-gray-800 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-[#A6CE39]"
)


class CariKelompokForm(forms.Form):
    """Form 'Cari Kelompok' — cocok dengan desain Figma (Nama Lengkap + Jurusan)."""

    nama_lengkap = forms.CharField(
        label="Nama Lengkap",
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Masukkan nama lengkap", "class": INPUT_CLASSES}),
    )
    jurusan = forms.ChoiceField(
        label="Jurusan",
        choices=[("", "Pilih Jurusan")] + JURUSAN_CHOICES,
        widget=forms.Select(attrs={"class": INPUT_CLASSES}),
    )


class MabaLoginForm(forms.Form):
    """Login form dipakai sampai integrasi SSO UI resmi terpasang (lihat siwak/sso.py)."""

    npm = forms.CharField(label="NPM", max_length=20, widget=forms.TextInput(attrs={"class": INPUT_CLASSES}))
    nama_lengkap = forms.CharField(
        label="Nama Lengkap", max_length=200, widget=forms.TextInput(attrs={"class": INPUT_CLASSES})
    )
    jurusan = forms.ChoiceField(
        label="Jurusan", choices=JURUSAN_CHOICES, widget=forms.Select(attrs={"class": INPUT_CLASSES})
    )
    angkatan = forms.CharField(
        label="Angkatan", max_length=4, required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASSES, "placeholder": "mis. 2026"}),
    )


class TugasSubmissionForm(forms.ModelForm):
    class Meta:
        model = TugasSubmission
        fields = ["file"]
        widgets = {
            "file": forms.ClearableFileInput(attrs={
                "class": "hidden",
                "accept": ".pdf,.docx,.jpg,.jpeg,.png",
            }),
        }

    def __init__(self, *args, tugas: Tugas = None, **kwargs):
        self.tugas = tugas
        super().__init__(*args, **kwargs)

    def clean_file(self):
        f = self.cleaned_data["file"]
        ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        if ext not in Tugas.ALLOWED_EXTENSIONS:
            raise ValidationError(
                "Format file tidak didukung. Gunakan PDF, DOCX, atau gambar (JPG/PNG)."
            )
        max_bytes = (self.tugas.max_file_size_mb if self.tugas else 10) * 1024 * 1024
        if f.size > max_bytes:
            limit = self.tugas.max_file_size_mb if self.tugas else 10
            raise ValidationError(f"Ukuran file melebihi batas {limit} MB.")
        return f


class RSVPForm(forms.ModelForm):
    class Meta:
        model = EventRSVP
        fields = ["catatan"]
        widgets = {
            "catatan": forms.Textarea(attrs={
                "class": INPUT_CLASSES, "rows": 3,
                "placeholder": "Ada catatan untuk panitia? (opsional)",
            }),
        }