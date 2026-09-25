from django import forms

from .models import (
    AssignmentReview,
    AssessmentAspect,
    MenteeAssessment,
    MentoringAttendance,
    Profile,
)


FIELD_CLASSES = (
    "w-full rounded-xl border-2 border-[#CBD5E1] bg-white px-3 py-2 "
    "text-sm text-slate-800 focus:border-navy focus:outline-none focus:ring-2 focus:ring-navy/20"
)


class MenteeSessionForm(forms.Form):
    """Attendance and the single editable feedback for one mentee in one session."""

    status = forms.ChoiceField(
        choices=[("", "Pilih status")] + MentoringAttendance.STATUS_CHOICES,
        widget=forms.Select(attrs={"class": FIELD_CLASSES}),
    )
    catatan = forms.CharField(
        required=False,
        max_length=300,
        widget=forms.TextInput(
            attrs={"class": FIELD_CLASSES, "placeholder": "Catatan presensi opsional"}
        ),
    )
    feedback = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": FIELD_CLASSES,
                "rows": 3,
                "placeholder": "Tambahkan feedback perkembangan pada sesi ini",
            }
        ),
    )

    def __init__(self, *args, existing_attendance=None, existing_feedback=None, **kwargs):
        super().__init__(*args, **kwargs)
        # `initial` dipasang juga saat bound supaya `has_changed()` bisa dipakai
        # halaman rekap untuk hanya menyimpan baris yang benar-benar disunting.
        if existing_attendance:
            self.initial.update(
                {
                    "status": existing_attendance.status,
                    "catatan": existing_attendance.catatan,
                }
            )
        if existing_feedback:
            self.initial["feedback"] = existing_feedback.isi


class MenteeAssessmentForm(forms.Form):
    """Dynamic 0-100 assessment fields for all currently active aspects."""

    def __init__(self, *args, participant, aspects=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.participant = participant
        self.aspects = list(aspects or AssessmentAspect.objects.filter(is_active=True))
        existing = {
            assessment.aspect_id: assessment
            for assessment in participant.assessments.filter(aspect__in=self.aspects)
        }

        for aspect in self.aspects:
            assessment = existing.get(aspect.pk)
            self.fields[f"score_{aspect.pk}"] = forms.IntegerField(
                label=aspect.nama,
                min_value=0,
                max_value=100,
                required=False,
                initial=assessment.score if assessment else None,
                widget=forms.NumberInput(
                    attrs={"class": FIELD_CLASSES, "min": 0, "max": 100, "placeholder": "0-100"}
                ),
            )
            self.fields[f"catatan_{aspect.pk}"] = forms.CharField(
                label=f"Catatan {aspect.nama}",
                required=False,
                initial=assessment.catatan if assessment else "",
                widget=forms.Textarea(
                    attrs={"class": FIELD_CLASSES, "rows": 2, "placeholder": "Catatan opsional"}
                ),
            )

    def clean(self):
        cleaned_data = super().clean()
        for aspect in self.aspects:
            score = cleaned_data.get(f"score_{aspect.pk}")
            note = cleaned_data.get(f"catatan_{aspect.pk}", "").strip()
            if score is None and note:
                self.add_error(
                    f"score_{aspect.pk}",
                    "Isi nilai terlebih dahulu sebelum menambahkan catatan.",
                )
        return cleaned_data


class CatatanMenteeForm(forms.ModelForm):
    """Catatan privat satu mentee (`Profile.notes`).

    Dipakai halaman mentor dan panel pengurus lewat satu view yang sama
    (`mentor_views.mentee_catatan`), jadi yang dibersihkan di sini hanya isinya;
    siapa yang boleh menyimpan diperiksa view itu.
    """

    class Meta:
        model = Profile
        fields = ["notes"]
        widgets = {
            "notes": forms.Textarea(
                attrs={
                    "class": FIELD_CLASSES,
                    "rows": 4,
                    "placeholder": "Catatan privat tentang mentee ini",
                }
            ),
        }


class AssignmentReviewForm(forms.ModelForm):
    class Meta:
        model = AssignmentReview
        fields = ["score", "feedback"]
        widgets = {
            "score": forms.NumberInput(
                attrs={"class": FIELD_CLASSES, "min": 0, "max": 100, "placeholder": "0-100"}
            ),
            "feedback": forms.Textarea(
                attrs={"class": FIELD_CLASSES, "rows": 5, "placeholder": "Feedback untuk mentee"}
            ),
        }

