from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .mentor_forms import (
    AssignmentReviewForm,
    MenteeAssessmentForm,
    MenteeSessionForm,
)
from .models import (
    AssignmentReview,
    AssignmentReviewHistory,
    AssessmentAspect,
    KelompokMentoring,
    MentoringAttendance,
    MentorFeedback,
    PesertaMentoring,
    Tugas,
    TugasSubmission,
)
from .services.mentor import require_mentor, save_assessments, save_session_record


def _mentor_group_or_404(mentor, group_id):
    return get_object_or_404(
        KelompokMentoring.objects.filter(mentor_list=mentor).distinct(),
        pk=group_id,
    )


@login_required
def mentor_dashboard(request):
    mentor = require_mentor(request.user)
    group = mentor.kelompok if mentor.kelompok_id and mentor.kelompok.is_active else None
    mentee_cards = []
    session_count = 0
    task_count = 0

    if group:
        participants = list(
            group.peserta_list.select_related("maba", "maba__user")
            .annotate(
                assessment_count=Count("assessments", distinct=True),
                attendance_count=Count("mentoring_attendance", distinct=True),
                present_count=Count(
                    "mentoring_attendance",
                    filter=Q(mentoring_attendance__status=MentoringAttendance.STATUS_HADIR),
                    distinct=True,
                ),
            )
            .order_by("maba__nama_lengkap")
        )
        user_ids = [
            participant.maba.user_id
            for participant in participants
            if participant.maba.user_id
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
            participant_submissions = submissions_by_user.get(participant.maba.user_id, [])
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
        PesertaMentoring.objects.select_related("maba", "maba__user"),
        pk=participant_id,
        kelompok=group,
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
        return redirect(
            f"{reverse('siwak:mentor_mentee_detail', kwargs={'participant_id': participant.pk})}"
            "#penilaian"
        )

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
            review = assignment_target_form.save(commit=False)
            review.submission = assignment_target
            review.reviewer = mentor
            review.save()
            AssignmentReviewHistory.objects.create(
                submission=assignment_target,
                score=review.score,
                feedback=review.feedback,
                reviewer=mentor,
            )
            messages.success(request, "Nilai dan feedback assignment berhasil disimpan.")
            return redirect(
                f"{reverse('siwak:mentor_mentee_detail', kwargs={'participant_id': participant.pk})}"
                f"#assignment-{assignment_target.tugas_id}"
            )

    tasks = Tugas.objects.filter(is_active=True).prefetch_related(
        Prefetch(
            "submissions",
            queryset=TugasSubmission.objects.filter(user=participant.user).select_related(
                "mentor_review__reviewer"
            )
            if participant.maba.user_id
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
                "status": (
                    "Pending"
                    if submission is None
                    else "Late"
                    if submission.status == "late"
                    else "Submitted"
                ),
            }
        )

    sessions = group.mentoring_sessions.prefetch_related(
        Prefetch(
            "attendance_records",
            queryset=MentoringAttendance.objects.filter(peserta=participant),
            to_attr="participant_attendance",
        ),
        Prefetch(
            "mentee_feedback",
            queryset=MentorFeedback.objects.filter(peserta=participant).select_related("mentor"),
            to_attr="participant_feedback",
        ),
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
        session_target_form = MenteeSessionForm(
            request.POST,
            existing_attendance=existing_attendance,
            prefix=f"session_{session_target.pk}",
        )
        if session_target_form.is_valid():
            save_session_record(
                form=session_target_form,
                participant=participant,
                session=session_target,
                mentor=mentor,
            )
            messages.success(request, f"Presensi dan feedback {session_target.judul} tersimpan.")
            return redirect(
                f"{reverse('siwak:mentor_mentee_detail', kwargs={'participant_id': participant.pk})}"
                f"#session-{session_target.pk}"
            )

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
                    prefix=f"session_{session.pk}",
                )
            )
        session_cards.append(
            {
                "session": session,
                "attendance": existing_attendance,
                "form": form,
                "feedback_entries": session.participant_feedback,
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
        },
    )


@login_required
def assignments(request, group_id):
    mentor = require_mentor(request.user)
    group = _mentor_group_or_404(mentor, group_id)
    participants = list(
        group.peserta_list.select_related("maba", "maba__user").order_by(
            "maba__nama_lengkap"
        )
    )
    user_ids = [
        participant.maba.user_id
        for participant in participants
        if participant.maba.user_id
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
                (task.pk, participant.maba.user_id)
            )
            participant_tasks.append(
                {
                    "task": task,
                    "submission": submission,
                    "status": (
                        "Pending"
                        if submission is None
                        else "Late"
                        if submission.status == "late"
                        else "Submitted"
                    ),
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
    participants = PesertaMentoring.objects.filter(maba__user=request.user)
    feedback_entries = MentorFeedback.objects.filter(peserta__in=participants).select_related(
        "session", "mentor", "peserta"
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
def submission_download(request, submission_id):
    submission = get_object_or_404(
        TugasSubmission.objects.select_related("user", "tugas"),
        pk=submission_id,
    )
    is_owner = submission.user_id == request.user.id
    mentor = getattr(request.user, "mentor_profile", None)
    is_responsible_mentor = bool(
        mentor
        and PesertaMentoring.objects.filter(
            maba__user=submission.user,
            kelompok__mentor_list=mentor,
        ).exists()
    )
    if not (is_owner or is_responsible_mentor or request.user.is_staff):
        raise Http404
    if not submission.file:
        raise Http404

    return FileResponse(
        submission.file.open("rb"),
        as_attachment=True,
        filename=Path(submission.file.name).name,
    )
