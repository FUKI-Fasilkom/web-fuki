from django.core.exceptions import PermissionDenied
from django.db import transaction

from siwak.models import MenteeAssessment, MentoringAttendance, Mentor, MentorFeedback


def mentor_for_user(user):
    if not user or not user.is_authenticated:
        return None
    return Mentor.objects.filter(user=user).first()


def require_mentor(user):
    mentor = mentor_for_user(user)
    if mentor is None:
        raise PermissionDenied("Halaman ini hanya dapat diakses oleh mentor.")
    return mentor


@transaction.atomic
def save_session_record(*, form, participant, session, mentor):
    attendance, _ = MentoringAttendance.objects.update_or_create(
        session=session,
        peserta=participant,
        defaults={
            "status": form.cleaned_data["status"],
            "catatan": form.cleaned_data["catatan"].strip(),
            "recorded_by": mentor,
        },
    )
    feedback_text = form.cleaned_data["feedback"].strip()
    if feedback_text:
        MentorFeedback.objects.create(
            session=session,
            peserta=participant,
            mentor=mentor,
            isi=feedback_text,
        )
    return attendance


@transaction.atomic
def save_assessments(*, form, participant, mentor):
    for aspect in form.aspects:
        score = form.cleaned_data.get(f"score_{aspect.pk}")
        if score is None:
            continue
        MenteeAssessment.objects.update_or_create(
            peserta=participant,
            aspect=aspect,
            defaults={
                "score": score,
                "catatan": form.cleaned_data[f"catatan_{aspect.pk}"].strip(),
                "assessed_by": mentor,
            },
        )
