from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from .models import (
    JURUSAN_CHOICES,
    EventRSVP,
    Question,
    Tugas,
    TugasSubmission,
)

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
    name = forms.CharField(
        label="Nama",
        disabled=True,
    )

    npm = forms.CharField(
        label="NPM",
        disabled=True,
        validators=[
            RegexValidator(
                regex=r"^\d+$",
                message="NPM hanya boleh berisi angka.",
            )
        ],
    )

    class Meta:
        model = EventRSVP
        fields = ["npm", "kehadiran", "alasan_izin"]
        widgets = {
            "kehadiran": forms.RadioSelect(),
            "alasan_izin": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Ex: acara keluarga",
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if user:
            profile = getattr(user, "maba_profile", None)
            self.fields["name"].initial = profile.nama_lengkap if profile else ""
            self.fields["npm"].initial = profile.npm if profile else ""

        if not self.initial.get("kehadiran"):
            self.initial["kehadiran"] = "hadir"

    def clean(self):
        cleaned_data = super().clean()
        kehadiran = cleaned_data.get("kehadiran")
        alasan_izin = cleaned_data.get("alasan_izin")
        if kehadiran == "izin" and not (alasan_izin or "").strip():
            self.add_error("alasan_izin", "Alasan izin wajib diisi jika kehadiran memilih Izin.")
        return cleaned_data

class TugasAnswerForm(forms.Form):
    def __init__(self, *args, tugas=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tugas = tugas

        if not tugas:
            return

        for question in tugas.questions.prefetch_related("choices").all():
            field_name = f"question_{question.id}"

            if question.tipe == "text":
                self.fields[field_name] = forms.CharField(
                    label=question.pertanyaan,
                    required=True,
                    widget=forms.Textarea(
                        attrs={
                            "rows": 5,
                            "class": INPUT_CLASSES,
                            "placeholder": "Tulis jawaban kamu...",
                        }
                    ),
                )

            elif question.tipe == "choice":
                self.fields[field_name] = forms.ChoiceField(
                    label=question.pertanyaan,
                    required=True,
                    choices=[
                        (choice.id, choice.teks)
                        for choice in question.choices.all()
                    ],
                    widget=forms.RadioSelect(),
                )

            elif question.tipe == "file":
                self.fields[field_name] = forms.FileField(
                    label=question.pertanyaan,
                    required=True,
                    widget=forms.ClearableFileInput(
                        attrs={
                            "accept": ".pdf,.docx,.jpg,.jpeg,.png",
                        }
                    ),
                )