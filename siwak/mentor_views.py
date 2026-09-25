from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST
from storages.backends.s3 import S3Storage

from .mentor_forms import (
    AssignmentReviewForm,
    CatatanMenteeForm,
    MenteeAssessmentForm,
    MenteeSessionForm,
)
from .models import (
    AssignmentReview,
    AssignmentReviewHistory,
    AssessmentAspect,
    KelompokMentoring,
    Profile,
    MentoringAttendance,
    MentorFeedback,
    Tugas,
    TugasSubmission,
)
from .services.mentor import (
    boleh_ubah_catatan,
    memegang_mentee,
    require_mentor,
    save_assessments,
    save_assignment_review,
    save_attendance_row,
)
from .utils import kembali, kueri_tanpa_halaman

PER_HALAMAN = 20


def _mentor_group_or_404(mentor, group_id):
    # `anggota=mentor`: kelompok ini hanya boleh dibuka oleh mentor yang memegangnya.
    return get_object_or_404(KelompokMentoring, pk=group_id, anggota=mentor)


def _mentor_dan_kelompok_aktif(request):
    """Mentor yang login + kelompok aktifnya, atau group=None kalau belum punya."""
    mentor = require_mentor(request.user)
    group = mentor.kelompok if mentor.kelompok_id and mentor.kelompok.is_active else None
    return mentor, group


def _status_tugas(submission):
    """Label status satu tugas di portal mentor."""
    if submission is None:
        return "Pending"
    return "Late" if submission.status == "late" else "Submitted"


def _feedback_terbaru(entries, kunci):
    """Feedback terbaru per `kunci(entry)`.

    Feedback disunting, bukan ditumpuk (satu per sesi per mentor), jadi kalau
    masih ada baris lama sisa sistem log, cuma yang terbaru yang dipakai.
    """
    terbaru = {}
    for entry in entries.order_by("-created_at"):
        terbaru.setdefault(kunci(entry), entry)
    return terbaru


def _ke_mentee(participant, jangkar):
    """Kembali ke bagian `jangkar` di halaman detail mentee sesudah menyimpan."""
    url = reverse("siwak:mentor_mentee_detail", kwargs={"participant_id": participant.pk})
    return redirect(f"{url}#{jangkar}")


@login_required
def mentor_dashboard(request):
    mentor, group = _mentor_dan_kelompok_aktif(request)
    mentee_cards = []
    session_count = 0
    task_count = 0

    if group:
        participants = list(
            group.daftar_mentee.select_related("user")
            .annotate(
                assessment_count=Count("assessments", distinct=True),
                attendance_count=Count("mentoring_attendance", distinct=True),
                present_count=Count(
                    "mentoring_attendance",
                    filter=Q(mentoring_attendance__status=MentoringAttendance.STATUS_HADIR),
                    distinct=True,
                ),
            )
            .order_by("nama_lengkap")
        )
        user_ids = [
            participant.user_id
            for participant in participants
            if participant.user_id
        ]
        active_tasks = list(Tugas.objects.filter(is_active=True))
        task_count = len(active_tasks)
        submissions = TugasSubmission.objects.filter(
            tugas__in=active_tasks,
            user_id__in=user_ids,
        )
        submissions_by_user = {}
        for submission in submissions:
            submissions_by_user.setdefault(submission.user_id, []).append(submission)

        aspect_count = AssessmentAspect.objects.filter(is_active=True).count()
        session_count = group.mentoring_sessions.filter(is_active=True).count()
        for participant in participants:
            participant_submissions = submissions_by_user.get(participant.user_id, [])
            submitted_count = len(participant_submissions)
            mentee_cards.append(
                {
                    "participant": participant,
                    "submitted_count": submitted_count,
                    "pending_count": max(task_count - submitted_count, 0),
                    "late_count": sum(
                        submission.status == "late" for submission in participant_submissions
                    ),
                    "aspect_count": aspect_count,
                }
            )

    return render(
        request,
        "siwak/mentor/dashboard.html",
        {
            "mentor": mentor,
            "group": group,
            "mentee_cards": mentee_cards,
            "session_count": session_count,
            "task_count": task_count,
        },
    )


@login_required
def mentee_detail(request, participant_id):
    mentor = require_mentor(request.user)
    if not mentor.kelompok_id:
        raise Http404
    group = mentor.kelompok
    participant = get_object_or_404(
        Profile.objects.select_related("user"),
        pk=participant_id,
        kelompok=group,
        role=Profile.ROLE_MENTEE,
    )

    action = request.POST.get("action") if request.method == "POST" else None
    aspects = list(AssessmentAspect.objects.filter(is_active=True))
    assessment_form = MenteeAssessmentForm(
        request.POST if action == "assessment" else None,
        participant=participant,
        aspects=aspects,
    )
    if action == "assessment" and assessment_form.is_valid():
        save_assessments(form=assessment_form, participant=participant, mentor=mentor)
        messages.success(request, "Penilaian mentee berhasil disimpan.")
        return _ke_mentee(participant, "penilaian")

    assessment_rows = [
        {
            "aspect": aspect,
            "score_field": assessment_form[f"score_{aspect.pk}"],
            "note_field": assessment_form[f"catatan_{aspect.pk}"],
        }
        for aspect in aspects
    ]
    saved_assessments = list(
        participant.assessments.filter(aspect__in=aspects).select_related("aspect")
    )
    assessment_average = (
        round(sum(item.score for item in saved_assessments) / len(saved_assessments), 1)
        if saved_assessments
        else None
    )

    attendance_records = list(
        participant.mentoring_attendance.select_related("session", "recorded_by")
    )
    present_count = sum(
        item.status == MentoringAttendance.STATUS_HADIR for item in attendance_records
    )

    assignment_target = None
    assignment_target_form = None
    if action == "assignment_review":
        assignment_target = get_object_or_404(
            TugasSubmission.objects.select_related("tugas", "user"),
            pk=request.POST.get("submission_id"),
            user=participant.user,
            tugas__is_active=True,
        )
        current_review = AssignmentReview.objects.filter(
            submission=assignment_target
        ).first()
        assignment_target_form = AssignmentReviewForm(
            request.POST,
            instance=current_review,
            prefix=f"assignment_{assignment_target.pk}",
        )
        if assignment_target_form.is_valid():
            save_assignment_review(
                form=assignment_target_form, submission=assignment_target, mentor=mentor
            )
            messages.success(request, "Nilai dan feedback assignment berhasil disimpan.")
            return _ke_mentee(participant, f"assignment-{assignment_target.tugas_id}")

    tasks = Tugas.objects.filter(is_active=True).prefetch_related(
        Prefetch(
            "submissions",
            queryset=TugasSubmission.objects.filter(user=participant.user).select_related(
                "mentor_review__reviewer"
            ).prefetch_related("answers__question", "answers__selected_choice")
            if participant.user_id
            else TugasSubmission.objects.none(),
            to_attr="participant_submissions",
        )
    )
    assignment_rows = []
    for task in tasks:
        submission = task.participant_submissions[0] if task.participant_submissions else None
        review = getattr(submission, "mentor_review", None) if submission else None
        review_form = None
        if submission:
            review_form = (
                assignment_target_form
                if assignment_target and submission.pk == assignment_target.pk
                else AssignmentReviewForm(
                    instance=review,
                    prefix=f"assignment_{submission.pk}",
                )
            )
        assignment_rows.append(
            {
                "task": task,
                "submission": submission,
                "review": review,
                "review_form": review_form,
                "review_history": (
                    submission.mentor_review_history.select_related("reviewer")
                    if submission
                    else []
                ),
                "status": _status_tugas(submission),
            }
        )

    sessions = list(
        group.mentoring_sessions.prefetch_related(
            Prefetch(
                "attendance_records",
                queryset=MentoringAttendance.objects.filter(peserta=participant),
                to_attr="participant_attendance",
            ),
        )
    )
    # Feedback milik mentor ini per sesi; itulah yang disunting, sama seperti
    # halaman rekap presensi.
    feedback_by_session = _feedback_terbaru(
        MentorFeedback.objects.filter(session__in=sessions, peserta=participant, mentor=mentor),
        lambda entry: entry.session_id,
    )

    session_target = None
    session_target_form = None
    if action == "session_record":
        session_target = get_object_or_404(
            group.mentoring_sessions,
            pk=request.POST.get("session_id"),
            is_active=True,
        )
        existing_attendance = MentoringAttendance.objects.filter(
            session=session_target,
            peserta=participant,
        ).first()
        existing_feedback = feedback_by_session.get(session_target.pk)
        session_target_form = MenteeSessionForm(
            request.POST,
            existing_attendance=existing_attendance,
            existing_feedback=existing_feedback,
            prefix=f"session_{session_target.pk}",
        )
        if session_target_form.is_valid():
            save_attendance_row(
                form=session_target_form,
                participant=participant,
                session=session_target,
                mentor=mentor,
                feedback_entry=existing_feedback,
            )
            messages.success(request, f"Presensi dan feedback {session_target.judul} tersimpan.")
            return _ke_mentee(participant, f"session-{session_target.pk}")

    session_cards = []
    for session in sessions:
        existing_attendance = (
            session.participant_attendance[0]
            if session.participant_attendance
            else None
        )
        form = None
        if session.is_active:
            form = (
                session_target_form
                if session_target and session.pk == session_target.pk
                else MenteeSessionForm(
                    existing_attendance=existing_attendance,
                    existing_feedback=feedback_by_session.get(session.pk),
                    prefix=f"session_{session.pk}",
                )
            )
        session_cards.append(
            {
                "session": session,
                "attendance": existing_attendance,
                "form": form,
            }
        )

    return render(
        request,
        "siwak/mentor/mentee_detail.html",
        {
            "mentor": mentor,
            "group": group,
            "participant": participant,
            "assessment_form": assessment_form,
            "assessment_rows": assessment_rows,
            "assessment_average": assessment_average,
            "attendance_records": attendance_records,
            "present_count": present_count,
            "assignment_rows": assignment_rows,
            "session_cards": session_cards,
            # Halaman ini memang hanya terbuka untuk mentor kelompoknya, tapi
            # aturan catatan tetap dibaca dari satu sumber yang sama.
            "boleh_catatan": boleh_ubah_catatan(request.user, participant),
            "catatan_form": CatatanMenteeForm(instance=participant),
        },
    )


@login_required
@require_POST
def mentee_catatan(request, participant_id):
    """Simpan catatan privat (`Profile.notes`) satu mentee.

    Hanya mentor kelompok mentee itu yang boleh (`boleh_ubah_catatan`).
    Pengurus membacanya di panel tanpa bisa mengubah, jadi pengurus pun mendapat
    403 di sini — begitu juga mentee itu sendiri, mentee lain, dan mentor
    kelompok lain. Penjaganya di sini, bukan hanya di templat: form yang
    disembunyikan tidak menghalangi POST yang dikirim langsung.
    """
    participant = get_object_or_404(Profile, pk=participant_id, role=Profile.ROLE_MENTEE)
    if not boleh_ubah_catatan(request.user, participant):
        raise PermissionDenied("Catatan ini hanya bisa diubah mentor kelompoknya.")

    form = CatatanMenteeForm(request.POST, instance=participant)
    if form.is_valid():
        form.save()
        if participant.notes.strip():
            messages.success(request, f"Catatan untuk {participant.nama_lengkap} tersimpan.")
        else:
            messages.success(request, f"Catatan untuk {participant.nama_lengkap} dihapus.")
    else:
        messages.error(request, "Catatan belum tersimpan. Periksa isiannya lalu coba lagi.")

    return kembali(
        request, reverse("siwak:mentor_mentee_detail", kwargs={"participant_id": participant.pk})
    )


@login_required
def assignments(request, group_id):
    mentor = require_mentor(request.user)
    group = _mentor_group_or_404(mentor, group_id)
    participants = list(
        group.daftar_mentee.select_related("user").order_by("nama_lengkap")
    )
    user_ids = [
        participant.user_id
        for participant in participants
        if participant.user_id
    ]
    tasks = Tugas.objects.all().prefetch_related(
        Prefetch(
            "submissions",
            queryset=TugasSubmission.objects.filter(user_id__in=user_ids).select_related(
                "user", "mentor_review__reviewer"
            ),
            to_attr="group_submissions",
        )
    )
    submissions_by_task_and_user = {
        (task.pk, submission.user_id): submission
        for task in tasks
        for submission in task.group_submissions
    }
    rows = []
    for participant in participants:
        participant_tasks = []
        for task in tasks:
            submission = submissions_by_task_and_user.get(
                (task.pk, participant.user_id)
            )
            participant_tasks.append(
                {
                    "task": task,
                    "submission": submission,
                    "status": _status_tugas(submission),
                }
            )
        rows.append({"participant": participant, "tasks": participant_tasks})

    return render(
        request,
        "siwak/mentor/assignments.html",
        {"mentor": mentor, "group": group, "rows": rows},
    )


@login_required
def mentee_feedback_history(request):
    feedback_by_session_mentor = _feedback_terbaru(
        MentorFeedback.objects.filter(peserta__user=request.user).select_related(
            "session", "mentor", "peserta"
        ),
        lambda entry: (entry.session_id, entry.mentor_id),
    )
    feedback_entries = sorted(
        feedback_by_session_mentor.values(),
        key=lambda entry: entry.created_at,
        reverse=True,
    )
    assignment_review_history = AssignmentReviewHistory.objects.filter(
        submission__user=request.user
    ).select_related("submission__tugas", "reviewer")
    return render(
        request,
        "siwak/mentee_feedback_history.html",
        {
            "feedback_entries": feedback_entries,
            "assignment_review_history": assignment_review_history,
        },
    )


@login_required
def answer_download(request, submission_id, answer_id):
    submission = get_object_or_404(
        TugasSubmission.objects.select_related("user", "tugas"),
        pk=submission_id,
    )
    is_owner = submission.user_id == request.user.id
    mentee = getattr(submission.user, "profil", None)
    is_responsible_mentor = mentee is not None and memegang_mentee(request.user, mentee)
    if not (is_owner or is_responsible_mentor or request.user.is_staff):
        raise Http404
    file = get_object_or_404(submission.answers, pk=answer_id).file_answer
    if not file:
        raise Http404

    if isinstance(file.storage, S3Storage):
        response = redirect(file.storage.url(
            file.name,
            parameters={"ResponseContentDisposition": content_disposition_header(
                True, Path(file.name).name
            )},
            expire=300,
        ))
        response["Cache-Control"] = "private, no-store"
        return response

    return FileResponse(
        file.open("rb"),
        as_attachment=True,
        filename=Path(file.name).name,
    )


# --- Halaman rekap mentor: presensi, nilai mentee, penilaian tugas ---------
#
# Ketiganya berbentuk satu <form> besar berisi banyak baris, dan boleh diisi
# sebagian: mentor yang baru sempat mengisi 3 dari 10 mentee tetap bisa
# menyimpan ketiganya.
#
#   * Baris yang tidak disentuh (`has_changed()` False) dilewati; datanya yang
#     lama tetap utuh. Baris yang isiannya sama sekali tidak ikut terkirim
#     (`_dikirim`) juga dianggap tidak disentuh.
#   * Setiap baris berdiri sendiri. Baris yang valid langsung disimpan walau ada
#     baris lain yang galat; baris yang galat tidak disimpan dan ditampilkan lagi
#     lengkap dengan isiannya.
#   * Form barisnya dibuat dengan `use_required_attribute=False`. Tanpa itu
#     Django menempelkan atribut HTML `required` ke isian wajib (status presensi,
#     nilai tugas) di SETIAP baris, dan peramban menolak mengirim form sebelum
#     semua baris terisi — aturan "wajib" per baris tetap dicek di server,
#     hanya untuk baris yang benar-benar diisi.


def _matches(query, *texts):
    return not query or any(query in (text or "").lower() for text in texts)


def _paginate(request, rows):
    halaman = Paginator(rows, PER_HALAMAN).get_page(request.GET.get("page"))
    return halaman, kueri_tanpa_halaman(request)


def _dikirim(request, prefix):
    """Apakah isian baris ber-`prefix` ini ikut terkirim di POST.

    Baris yang sama sekali tidak ada di kiriman diperlakukan seperti baris yang
    tidak disentuh — bukan sebagai baris yang dikosongkan. Tanpa ini, klien yang
    hanya mengirim baris yang diisinya membuat setiap baris lain ber-data lama
    terbaca "berubah jadi kosong" lalu galat.
    """
    awalan = f"{prefix}-"
    return request.method == "POST" and any(key.startswith(awalan) for key in request.POST)


def _rekap_selesai(request, saved_count, error_count):
    """Balasan sesudah POST.

    Ada baris galat: pesan (berapa yang sudah tersimpan, berapa yang belum) lalu
    None, supaya halaman digambar ulang dengan isian dan galatnya. Tanpa galat:
    PRG ke halaman yang sama.
    """
    if error_count:
        if saved_count:
            messages.success(request, f"{saved_count} baris berhasil disimpan.")
        messages.error(
            request,
            f"{error_count} baris belum valid dan belum disimpan. "
            "Perbaiki isian yang ditandai lalu simpan lagi.",
        )
        return None
    if saved_count:
        messages.success(request, f"{saved_count} baris berhasil disimpan.")
    else:
        messages.info(request, "Tidak ada perubahan yang perlu disimpan.")
    return redirect(request.get_full_path())


@login_required
def mentor_attendance(request):
    mentor, group = _mentor_dan_kelompok_aktif(request)
    if group is None:
        return render(request, "siwak/mentor/attendance.html", {"mentor": mentor, "group": None})

    query = request.GET.get("q", "").strip()
    sesi_filter = request.GET.get("sesi", "")
    participants = list(group.daftar_mentee.order_by("nama_lengkap"))
    sessions = list(group.mentoring_sessions.order_by("nomor"))

    attendance = {
        (a.session_id, a.peserta_id): a
        for a in MentoringAttendance.objects.filter(session__in=sessions, peserta__in=participants)
    }
    # Feedback milik mentor ini per (sesi, mentee); itulah yang disunting.
    feedback = _feedback_terbaru(
        MentorFeedback.objects.filter(
            session__in=sessions, peserta__in=participants, mentor=mentor
        ),
        lambda entry: (entry.session_id, entry.peserta_id),
    )

    rows = []
    for session in sessions:
        if sesi_filter and str(session.nomor) != sesi_filter:
            continue
        for participant in participants:
            if not _matches(query.lower(), participant.nama_lengkap, participant.npm, session.judul):
                continue
            rows.append({"session": session, "participant": participant})

    halaman, kueri = _paginate(request, rows)
    posting = request.method == "POST"
    error_count = 0
    valid = []
    for row in halaman.object_list:
        session, participant = row["session"], row["participant"]
        row["attendance"] = attendance.get((session.pk, participant.pk))
        row["feedback_entry"] = feedback.get((session.pk, participant.pk))
        # Sesi yang belum diaktifkan pengurus hanya dibaca (aturan yang sama
        # dengan halaman detail mentee).
        row["form"] = None
        if session.is_active:
            prefix = f"s{session.pk}m{participant.pk}"
            dikirim = _dikirim(request, prefix)
            row["form"] = MenteeSessionForm(
                request.POST if dikirim else None,
                existing_attendance=row["attendance"],
                existing_feedback=row["feedback_entry"],
                prefix=prefix,
                use_required_attribute=False,
            )
            if dikirim and row["form"].has_changed():
                if row["form"].is_valid():
                    valid.append(row)
                else:
                    error_count += 1

    if posting:
        for row in valid:
            save_attendance_row(
                form=row["form"],
                participant=row["participant"],
                session=row["session"],
                mentor=mentor,
                feedback_entry=row["feedback_entry"],
            )
        response = _rekap_selesai(request, len(valid), error_count)
        if response:
            return response

    return render(
        request,
        "siwak/mentor/attendance.html",
        {
            "mentor": mentor,
            "group": group,
            "halaman": halaman,
            "kueri": kueri,
            "q": query,
            "sesi": sesi_filter,
            "session_choices": sessions,
            "total_rows": len(rows),
            "editable_count": sum(1 for row in halaman.object_list if row["form"]),
        },
    )


@login_required
def mentor_assessments(request):
    mentor, group = _mentor_dan_kelompok_aktif(request)
    if group is None:
        return render(request, "siwak/mentor/assessments.html", {"mentor": mentor, "group": None})

    query = request.GET.get("q", "").strip()
    # Aspek diambil dari database, sama seperti di halaman detail mentee.
    aspects = list(AssessmentAspect.objects.filter(is_active=True))
    participants = [
        participant
        for participant in group.daftar_mentee.order_by("nama_lengkap")
        if _matches(query.lower(), participant.nama_lengkap, participant.npm)
    ]

    halaman, kueri = _paginate(request, participants)
    posting = request.method == "POST"
    error_count = 0
    valid = []
    rows = []
    for participant in halaman.object_list:
        prefix = f"m{participant.pk}"
        dikirim = _dikirim(request, prefix)
        form = MenteeAssessmentForm(
            request.POST if dikirim else None,
            participant=participant,
            aspects=aspects,
            prefix=prefix,
            use_required_attribute=False,
        )
        if dikirim and form.has_changed():
            if form.is_valid():
                valid.append((participant, form))
            else:
                error_count += 1
        rows.append(
            {
                "participant": participant,
                "form": form,
                "cells": [
                    {
                        "aspect": aspect,
                        "score_field": form[f"score_{aspect.pk}"],
                        "note_field": form[f"catatan_{aspect.pk}"],
                    }
                    for aspect in aspects
                ],
            }
        )

    if posting:
        for participant, form in valid:
            save_assessments(form=form, participant=participant, mentor=mentor)
        response = _rekap_selesai(request, len(valid), error_count)
        if response:
            return response

    return render(
        request,
        "siwak/mentor/assessments.html",
        {
            "mentor": mentor,
            "group": group,
            "halaman": halaman,
            "kueri": kueri,
            "q": query,
            "aspects": aspects,
            "rows": rows,
        },
    )


@login_required
def mentor_task_reviews(request):
    mentor, group = _mentor_dan_kelompok_aktif(request)
    if group is None:
        return render(request, "siwak/mentor/task_reviews.html", {"mentor": mentor, "group": None})

    query = request.GET.get("q", "").strip()
    tugas_filter = request.GET.get("tugas", "")
    status_filter = request.GET.get("status", "")
    participants = {
        participant.user_id: participant
        for participant in group.daftar_mentee.filter(user__isnull=False)
    }
    tasks = list(Tugas.objects.filter(is_active=True))

    submissions = TugasSubmission.objects.filter(
        user_id__in=participants.keys(), tugas__in=tasks
    ).select_related("tugas", "user", "mentor_review__reviewer").prefetch_related(
        "answers__question", "answers__selected_choice"
    )
    if tugas_filter.isdigit():
        submissions = submissions.filter(tugas_id=int(tugas_filter))
    if status_filter == "belum":
        submissions = submissions.filter(mentor_review__isnull=True)
    elif status_filter == "sudah":
        submissions = submissions.filter(mentor_review__isnull=False)

    rows = []
    for submission in submissions:
        participant = participants[submission.user_id]
        if _matches(
            query.lower(), participant.nama_lengkap, participant.npm, submission.tugas.judul_tugas
        ):
            rows.append({"submission": submission, "participant": participant})
    rows.sort(
        key=lambda row: (
            row["submission"].tugas.deadline,
            row["submission"].tugas_id,
            row["participant"].nama_lengkap,
        )
    )

    halaman, kueri = _paginate(request, rows)
    posting = request.method == "POST"
    error_count = 0
    valid = []
    for row in halaman.object_list:
        submission = row["submission"]
        row["review"] = getattr(submission, "mentor_review", None)
        prefix = f"t{submission.pk}"
        dikirim = _dikirim(request, prefix)
        row["form"] = AssignmentReviewForm(
            request.POST if dikirim else None,
            instance=row["review"],
            prefix=prefix,
            use_required_attribute=False,
        )
        if dikirim and row["form"].has_changed():
            if row["form"].is_valid():
                valid.append(row)
            else:
                error_count += 1

    if posting:
        for row in valid:
            save_assignment_review(
                form=row["form"], submission=row["submission"], mentor=mentor
            )
        response = _rekap_selesai(request, len(valid), error_count)
        if response:
            return response

    return render(
        request,
        "siwak/mentor/task_reviews.html",
        {
            "mentor": mentor,
            "group": group,
            "halaman": halaman,
            "kueri": kueri,
            "q": query,
            "tugas": tugas_filter,
            "status": status_filter,
            "task_choices": tasks,
            "total_rows": len(rows),
        },
    )
