from django.core.exceptions import PermissionDenied
from django.db import transaction

from siwak.models import (
    AssignmentReviewHistory,
    Profile,
    MenteeAssessment,
    MentoringAttendance,
    MentorFeedback,
)


def mentor_for_user(user):
    """Profil mentor milik `user`, atau None kalau dia bukan mentor."""
    if not user or not user.is_authenticated:
        return None
    return Profile.objects.filter(
        user=user, role=Profile.ROLE_MENTOR
    ).first()


def require_mentor(user):
    mentor = mentor_for_user(user)
    if mentor is None:
        raise PermissionDenied("Halaman ini hanya dapat diakses oleh mentor.")
    return mentor


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


@transaction.atomic
def save_attendance_row(*, form, participant, session, mentor, feedback_entry=None):
    """Simpan satu baris presensi + feedback sesi.

    Feedback disunting, bukan ditumpuk: `feedback_entry` adalah feedback milik
    mentor ini yang sudah ada untuk sesi & mentee tersebut, kalau ada. Teks
    dikosongkan = dihapus.
    """
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
        if feedback_entry is None:
            MentorFeedback.objects.create(
                session=session, peserta=participant, mentor=mentor, isi=feedback_text
            )
        elif feedback_entry.isi != feedback_text:
            feedback_entry.isi = feedback_text
            feedback_entry.save(update_fields=["isi", "updated_at"])
    elif feedback_entry is not None:
        feedback_entry.delete()
    return attendance


@transaction.atomic
def save_assignment_review(*, form, submission, mentor):
    """Simpan nilai tugas + tambah snapshot riwayat (dipakai halaman detail & rekap)."""
    review = form.save(commit=False)
    review.submission = submission
    review.reviewer = mentor
    review.save()
    AssignmentReviewHistory.objects.create(
        submission=submission,
        score=review.score,
        feedback=review.feedback,
        reviewer=mentor,
    )
    return review
