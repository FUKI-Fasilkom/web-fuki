from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.core.files.uploadedfile import UploadedFile

from .models import (
    EventRSVP,
    Question,
    Tugas,
)

INPUT_CLASSES = (
    "w-full rounded-xl border-[3px] border-[#3A3A3A] bg-[#EFEFEF] px-4 py-3 "
    "text-gray-800 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-[#A6CE39]"
)


class CariKelompokForm(forms.Form):
    """Form 'Cari Kelompok' — identitas mentee dapat berupa nama atau NPM."""

    nama_lengkap = forms.CharField(
        label="Nama Lengkap atau NPM",
        max_length=200,
        widget=forms.TextInput(
            attrs={"placeholder": "Masukkan nama lengkap atau NPM", "class": INPUT_CLASSES}
        ),
    )



def validate_tugas_file(file, tugas):
    # File lama boleh dipertahankan tanpa membaca ulang objek dari S3.
    if not isinstance(file, UploadedFile):
        return file
    ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""
    if ext not in Tugas.ALLOWED_EXTENSIONS:
        raise ValidationError("Format file tidak didukung. Gunakan PDF, DOCX, atau gambar (JPG/PNG).")
    limit = tugas.max_file_size_mb if tugas else 10
    if file.size > limit * 1024 * 1024:
        raise ValidationError(f"Ukuran file melebihi batas {limit} MB.")
    return file


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

        # Diisi template supaya label "Otomatis dari SSO" tidak dipasang di akun
        # yang memang tidak lewat SSO.
        self.akun_lokal = False

        if user:
            profile = getattr(user, "profil", None)
            self.fields["name"].initial = profile.nama_lengkap if profile else ""
            self.fields["npm"].initial = profile.npm if profile else ""
            # Mentor non-SSO tidak punya NPM (NULL, bukan salah data). Field ini
            # disabled, jadi nilainya selalu `initial`; kalau tetap wajib, "" dari
            # mentor lokal membuat form selalu tidak valid dan RSVP mustahil.
            if profile and profile.is_akun_lokal:
                self.akun_lokal = True
                self.fields["npm"].required = False

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
    def __init__(self, *args, tugas=None, submission=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tugas = tugas

        if not tugas:
            return

        answers = {a.question_id: a for a in submission.answers.all()} if submission else {}

        for question in tugas.questions.prefetch_related("choices").all():
            field_name = f"question_{question.id}"

            if question.tipe == "text":
                self.fields[field_name] = forms.CharField(
                    label=question.pertanyaan,
                    required=True,
                    # Gaya "garis bawah" ala Figma; 1 baris lalu tinggi menyesuaikan
                    # isi (lihat fitTextareas di tugas_detail.html).
                    widget=forms.Textarea(
                        attrs={
                            "rows": 1,
                            "class": (
                                "block w-full resize-none overflow-hidden border-0 "
                                "border-b border-[#8A8A8A] bg-transparent px-0 py-1 "
                                "text-base text-black placeholder-[#9A9A9A] "
                                "focus:border-[#001B3D] focus:outline-none focus:ring-0"
                            ),
                            "placeholder": "Tulis jawaban kamu...",
                            "oninput": "this.style.height='auto';this.style.height=this.scrollHeight+'px'",
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
                    widget=forms.FileInput(
                        attrs={
                            "class": "sr-only",
                            "accept": ".pdf,.docx,.jpg,.jpeg,.png",
                        }
                    ),
                )

            answer = answers.get(question.pk)
            if answer:
                self.initial[field_name] = {
                    "text": answer.text_answer,
                    "choice": answer.selected_choice_id,
                    "file": answer.file_answer,
                }[question.tipe]

    def clean(self):
        cleaned = super().clean()
        for name, field in self.fields.items():
            if isinstance(field, forms.FileField) and cleaned.get(name):
                try:
                    validate_tugas_file(cleaned[name], self.tugas)
                except ValidationError as exc:
                    self.add_error(name, exc)
        return cleaned
