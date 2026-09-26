from django.db import transaction

from siwak.akses import AksesDitolak
from siwak.models import (
    MenteeAssessment,
    MentorFeedback,
    MentoringAttendance,
    Profile,
)


def require_mentor(user):
    """Profil mentor milik `user`; selain mentor mendapat halaman 403 "Akses Ditolak"."""
    mentor = None
    if user and user.is_authenticated:
        mentor = Profile.objects.filter(user=user, role=Profile.ROLE_MENTOR).first()
    if mentor is None:
        raise AksesDitolak("mentor")
    return mentor


def memegang_mentee(user, mentee):
    """Apakah `user` mentor yang memegang kelompok `mentee` (profil ber-role mentee).

    `mentee.kelompok_id` wajib dicek lebih dulu: filter `kelompok_id=None`
    di ORM berarti IS NULL, sehingga mentor tanpa kelompok akan "cocok" dengan
    setiap mentee yang belum ditempatkan.
    """
    if not user or not user.is_authenticated:
        return False
    if mentee.role != Profile.ROLE_MENTEE or not mentee.kelompok_id:
        return False
    return Profile.objects.filter(
        user=user, role=Profile.ROLE_MENTOR, kelompok_id=mentee.kelompok_id
    ).exists()


def boleh_ubah_catatan(user, mentee):
    """Siapa yang boleh menyunting `Profile.notes` milik `mentee`: hanya mentor
    yang memegang kelompok mentee itu. Pengurus hanya membaca (lihat
    `boleh_baca_catatan`) — catatan ini milik mentornya.
    """
    return memegang_mentee(user, mentee)


def boleh_baca_catatan(user, mentee):
    """Siapa yang boleh membaca `Profile.notes` milik `mentee`: pengurus
    (`is_staff`) dan mentor yang memegang kelompoknya. Mentee sendiri, mentee
    lain, dan mentor kelompok lain tidak pernah boleh."""
    if user and user.is_authenticated and user.is_staff:
        return True
    return boleh_ubah_catatan(user, mentee)


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


def save_assignment_review(*, form, submission, mentor):
    """Simpan feedback tugas, disunting di tempat (dipakai halaman detail & rekap)."""
    review = form.save(commit=False)
    review.submission = submission
    review.reviewer = mentor
    review.save()
    return review
