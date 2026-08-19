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

