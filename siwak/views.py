import calendar as pycal
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core import signing
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import CariKelompokForm, RSVPForm, TugasAnswerForm, TugasSubmissionForm
from .models import (
    EventRSVP,
    FAQMentoring,
    GaleriFoto,
    KetuaSiwak,
    MentoringBenefit,
    MentoringTujuan,
    PesertaMentoring,
    SistemMentoring,
    SiwakEvent,
    SiwakInfo,
    TimelineEvent,
    Tugas,
)
from .services.qrcode_service import (
    kupon_qr_data_uri,
    registrasi_qr_data_uri,
    unsign_payload,
)


def superuser_required(view_func):
    """Admin-only decorator for qr_verify.

    django.contrib.auth's `user_passes_test` (Django 6) redirects *every* user
    who fails the test to the login URL — even already-logged-in non-admins —
    which produces a redirect loop on `/admin/login/?next=...`. This mirrors
    Django's own `staff_member_required` instead: anonymous users are sent to
    the admin login, logged-in non-superusers get a clean 403.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated:
            if not request.user.is_superuser:
                return HttpResponseForbidden()
            return view_func(request, *args, **kwargs)
        return redirect_to_login(request.get_full_path(), reverse("admin:login"))

    return _wrapped


# ---------------------------------------------------------------------------
# 4.1 / 4.2 / 4.3 — Public informational page
# ---------------------------------------------------------------------------

def landing(request):
    """Single long-scroll landing page: mirrors the Figma SIWAK-NG page."""
    context = {
        "info": SiwakInfo.get_solo(),
        "events": SiwakEvent.objects.all(),
        "tujuan_list": MentoringTujuan.objects.all(),
        "benefit_list": MentoringBenefit.objects.all(),
        "sistem_list": SistemMentoring.objects.all(),
        "galeri_list": GaleriFoto.objects.all()[:6],
        "ketua_list": KetuaSiwak.objects.all(),
        "timeline_list": TimelineEvent.objects.filter(is_active=True),
        "faq_list": FAQMentoring.objects.all(),
    }
    return render(request, "siwak/landing.html", context)


def event_detail(request, pk):
    """Public detail page for a SIWAK event."""
    event = get_object_or_404(SiwakEvent, pk=pk)

    context = {
        "event": event,
        "info": SiwakInfo.get_solo(),
    }
    return render(request, "siwak/event_detail.html", context)


def kelompok_search(request):
    """4.3 — 'Cari Kelompok' search, matches the Figma search + result screens."""
    form = CariKelompokForm(request.POST or None)
    result_state = None  # None | "not_found" | "no_group_yet" | "found"
    peserta = None

    if request.method == "POST" and form.is_valid():
        peserta = PesertaMentoring.objects.filter(
            maba__nama_lengkap__iexact=form.cleaned_data["nama_lengkap"].strip(),
            maba__jurusan=form.cleaned_data["jurusan"],
        ).select_related("maba", "kelompok").prefetch_related("kelompok__mentor_list").first()

        if not peserta:
            result_state = "not_found"
        elif not peserta.kelompok:
            result_state = "no_group_yet"
        else:
            result_state = "found"

    context = {
        "form": form,
        "result_state": result_state,
        "peserta": peserta,
        "info": SiwakInfo.get_solo(),
    }
    return render(request, "siwak/kelompok_search.html", context)



# ---------------------------------------------------------------------------
# 5.1 — Slot Pengumpulan Tugas SIWAK
# ---------------------------------------------------------------------------

@login_required
def tugas_list(request):
    tugas_qs = Tugas.objects.filter(is_active=True)
    rows = []
    due_dates = set()

    for tugas in tugas_qs:
        submission = tugas.submission_for(request.user)

        if submission:
            status = "Submitted" if submission.status == "submitted" else "Late"
        else:
            status = "Not Submitted"

        rows.append({
            "tugas": tugas,
            "status": status,
            "submission": submission,
        })

        due_dates.add(tugas.deadline.date())

    today = timezone.localdate()

    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month

    cal = pycal.Calendar(firstweekday=6)  # Sunday-first, like the Figma calendar
    weeks = cal.monthdatescalendar(year, month)

    def shift_month(y, m, delta):
        m2 = m + delta
        y2 = y + (m2 - 1) // 12
        m2 = (m2 - 1) % 12 + 1
        return y2, m2

    prev_year, prev_m = shift_month(year, month, -1)
    next_year, next_m = shift_month(year, month, 1)

    context = {
        "rows": rows,
        "calendar_weeks": weeks,
        "cal_year": year,
        "cal_month": month,
        "cal_month_name": pycal.month_name[month],
        "cal_months": list(enumerate(pycal.month_name))[1:],
        "cal_years": range(today.year - 1, today.year + 2),
        "due_dates": due_dates,
        "today": today,
        "prev_year": prev_year,
        "prev_month": prev_m,
        "next_year": next_year,
        "next_month": next_m,
    }

    return render(request, "siwak/tugas_list.html", context)


@login_required
def tugas_detail(request, pk):
    tugas = get_object_or_404(Tugas, pk=pk, is_active=True)
    submission = tugas.submission_for(request.user)
    is_past_deadline = timezone.now() > tugas.deadline

    form = TugasAnswerForm(tugas=tugas)

    if request.method == "POST":
        if is_past_deadline:
            messages.error(request, "Tugas sudah melewati deadline.")
            return redirect("siwak:tugas_detail", pk=pk)

        form = TugasAnswerForm(
            request.POST,
            request.FILES,
            tugas=tugas,
        )

        if form.is_valid():
            if not submission:
                submission = tugas.submissions.model(
                    tugas=tugas,
                    user=request.user,
                )
                submission.save()

            for question in tugas.questions.all():
                field_name = f"question_{question.id}"
                value = form.cleaned_data.get(field_name)

                answer, _ = submission.answers.get_or_create(
                    question=question
                )

                if question.tipe == "text":
                    answer.text_answer = value
                    answer.selected_choice = None
                    answer.file_answer = None

                elif question.tipe == "choice":
                    answer.selected_choice_id = value
                    answer.text_answer = ""
                    answer.file_answer = None

                elif question.tipe == "file":
                    answer.file_answer = value
                    answer.text_answer = ""
                    answer.selected_choice = None

                answer.save()

            messages.success(request, "Tugas berhasil dikirim.")
            return redirect("siwak:tugas_detail", pk=pk)

    context = {
        "tugas": tugas,
        "submission": submission,
        "assignment_review": (
            getattr(submission, "mentor_review", None) if submission else None
        ),
        "is_past_deadline": is_past_deadline,
        "form": form,
    }

    return render(request, "siwak/tugas_detail.html", context)

# ---------------------------------------------------------------------------
# 5.2 / 6 — RSVP + QR Registrasi Ulang & QR Kupon Makan
# ---------------------------------------------------------------------------

@login_required
def rsvp_event(request, id):
    # 404 hanya kalau event benar-benar tidak ada/dihapus (tanpa login: tetap 404).
    # Kalau event ada tapi RSVP-nya sudah ditutup, tampilkan halaman "RSVP ditutup"
    # (kecuali user sudah pernah RSVP — mereka tetap bisa melihat QR-nya).
    event = get_object_or_404(SiwakEvent, id=id)
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    rsvp = EventRSVP.objects.filter(event=event, user=request.user).first()
    if not event.rsvp_dibuka and not rsvp:
        context = {
            "event": event,
            "rsvp_ditutup": True,
            "back_url": reverse("siwak:landing"),
        }
        return render(request, "siwak/rsvp.html", context)

    form = RSVPForm(user=request.user)
    if request.method == "POST" and not rsvp:
        form = RSVPForm(request.POST, user=request.user)
        if form.is_valid():
            rsvp = form.save(commit=False)
            rsvp.event = event
            rsvp.user = request.user
            rsvp.save()
            messages.success(request, "RSVP berhasil! QR code kamu sudah siap.")
            return redirect("siwak:rsvp", id=id)

    context = {
        "event": event,
        "rsvp": rsvp,
        "form": form,
        "back_url": reverse("siwak:landing"),
    }
    if rsvp:
        context["qr_registrasi"] = registrasi_qr_data_uri(request, rsvp)
        context["qr_kupon"] = kupon_qr_data_uri(request, rsvp)

    return render(request, "siwak/rsvp.html", context)


def _find_rsvp(kind: str, token: str, lock: bool = False):
    """Find the RSVP referenced by a signed QR payload.

    `lock=True` re-selects the row with ``SELECT ... FOR UPDATE`` so concurrent
    scans serialize instead of both succeeding (TOCTOU check-in / kupon).
    """
    field = "qr_registrasi_token" if kind == "registrasi" else "qr_kupon_token"
    qs = EventRSVP.objects.filter(**{field: token}).select_related("user", "event")
    if lock:
        qs = qs.select_for_update()
    return qs.first()


@superuser_required
@require_http_methods(["GET", "POST"])
def qr_verify(request, signed):
    """Scanned-QR landing page (PRD 6.1/6.2). Superuser-only.

    GET is read-only: it only renders a *confirmation* page. The actual
    check-in / kupon redemption happens on a CSRF-protected POST, so a passive
    ``<img src=".../qr/...">`` load in an admin's browser can't flip
    attendance state. The POST runs inside a transaction with
    ``SELECT ... FOR UPDATE`` on the RSVP row, so two concurrent scans can't
    both succeed (TOCTOU).
    """
    error = None
    rsvp = None
    kind = None
    already = False

    try:
        payload = unsign_payload(signed)
        kind = payload["kind"]
        token = payload["token"]

    except signing.SignatureExpired:
        error = "QR sudah kedaluwarsa."

    except signing.BadSignature:
        error = "QR tidak valid atau rusak."

    if not error and request.method == "POST":
        # Mutation path: lock the row so concurrent scans serialize.
        with transaction.atomic():
            rsvp = _find_rsvp(kind, token, lock=True)

            if not rsvp:
                error = "Data RSVP tidak ditemukan."

            elif kind == "registrasi":
                already = rsvp.status_kehadiran == "hadir"

                if not already:
                    if rsvp.kehadiran != "hadir":
                        error = "Check-in ditolak: kehadiran RSVP peserta bukan 'hadir'."
                    else:
                        rsvp.status_kehadiran = "hadir"
                        rsvp.checked_in_at = timezone.now()

                        rsvp.save(
                            update_fields=[
                                "status_kehadiran",
                                "checked_in_at",
                            ]
                        )

            elif kind == "kupon":
                already = rsvp.status_kupon == "redeemed"

                if not already:
                    rsvp.status_kupon = "redeemed"
                    rsvp.redeemed_at = timezone.now()

                    rsvp.save(
                        update_fields=[
                            "status_kupon",
                            "redeemed_at",
                        ]
                    )

    elif not error:
        # Read-only preview: resolve the row so the page can show a confirm step.
        rsvp = _find_rsvp(kind, token)

        if not rsvp:
            error = "Data RSVP tidak ditemukan."

        else:
            already = (
                rsvp.status_kehadiran == "hadir"
                if kind == "registrasi"
                else rsvp.status_kupon == "redeemed"
            )

    context = {
        "error": error,
        "rsvp": rsvp,
        "kind": kind,
        "already": already,
        "confirm": (
            request.method == "GET"
            and rsvp is not None
            and not error
            and not already
        ),
        "back_url": reverse("siwak:landing"),
    }

    return render(request, "siwak/qr_verify.html", context)
