import calendar as pycal

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import logout as django_logout
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import CariKelompokForm, MabaLoginForm, RSVPForm, TugasSubmissionForm
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
from .sso import login_or_create_maba


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


def kelompok_search(request):
    """4.3 — 'Cari Kelompok' search, matches the Figma search + result screens."""
    form = CariKelompokForm(request.POST or None)
    result_state = None  # None | "not_found" | "no_group_yet" | "found"
    peserta = None

    if request.method == "POST" and form.is_valid():
        peserta = PesertaMentoring.objects.filter(
            nama_lengkap__iexact=form.cleaned_data["nama_lengkap"].strip(),
            jurusan=form.cleaned_data["jurusan"],
        ).select_related("kelompok").prefetch_related("kelompok__mentors").first()

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
# 7 — Authentication (dev-mode stand-in for SSO UI; see siwak/sso.py)
# ---------------------------------------------------------------------------

def maba_login(request):
    if request.user.is_authenticated:
        return redirect(request.GET.get("next") or "siwak:tugas_list")

    form = MabaLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login_or_create_maba(
            request,
            npm=form.cleaned_data["npm"].strip(),
            nama_lengkap=form.cleaned_data["nama_lengkap"].strip(),
            jurusan=form.cleaned_data["jurusan"],
            angkatan=form.cleaned_data["angkatan"].strip(),
        )
        messages.success(request, "Berhasil masuk.")
        return redirect(request.GET.get("next") or "siwak:tugas_list")

    return render(request, "siwak/login.html", {"form": form})


@login_required
def maba_logout(request):
    django_logout(request)
    messages.info(request, "Kamu telah keluar.")
    return redirect("siwak:landing")


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
        rows.append({"tugas": tugas, "status": status, "submission": submission})
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
        "prev_year": prev_year, "prev_month": prev_m,
        "next_year": next_year, "next_month": next_m,
    }
    return render(request, "siwak/tugas_list.html", context)


@login_required
def tugas_detail(request, pk):
    tugas = get_object_or_404(Tugas, pk=pk, is_active=True)
    submission = tugas.submission_for(request.user)
    is_past_deadline = timezone.now() > tugas.deadline

    form = TugasSubmissionForm(tugas=tugas)
    if request.method == "POST":
        form = TugasSubmissionForm(request.POST, request.FILES, tugas=tugas)
        if form.is_valid():
            if submission:
                submission.file = form.cleaned_data["file"]
            else:
                submission = tugas.submissions.model(tugas=tugas, user=request.user, file=form.cleaned_data["file"])
            submission.save()
            messages.success(request, "Tugas berhasil dikirim.")
            return redirect("siwak:tugas_detail", pk=pk)

    context = {
        "tugas": tugas,
        "submission": submission,
        "is_past_deadline": is_past_deadline,
        "form": form,
    }
    return render(request, "siwak/tugas_detail.html", context)


# ---------------------------------------------------------------------------
# 5.2 / 6 — RSVP + QR Registrasi Ulang & QR Kupon Makan
# ---------------------------------------------------------------------------

@login_required
def rsvp_event(request, tipe):
    event = get_object_or_404(SiwakEvent, tipe=tipe, rsvp_dibuka=True)
    rsvp = EventRSVP.objects.filter(event=event, user=request.user).first()

    form = RSVPForm()
    if request.method == "POST" and not rsvp:
        form = RSVPForm(request.POST)
        if form.is_valid():
            rsvp = form.save(commit=False)
            rsvp.event = event
            rsvp.user = request.user
            rsvp.save()
            messages.success(request, "RSVP berhasil! QR code kamu sudah siap.")
            return redirect("siwak:rsvp", tipe=tipe)

    context = {"event": event, "rsvp": rsvp, "form": form}
    if rsvp:
        context["qr_registrasi"] = registrasi_qr_data_uri(request, rsvp)
        context["qr_kupon"] = kupon_qr_data_uri(request, rsvp)
    return render(request, "siwak/rsvp.html", context)


@staff_member_required
def qr_verify(request, signed):
    """Landing page for a scanned QR (PRD 6.1/6.2). Staff-only, one-time use."""
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

    if not error:
        if kind == "registrasi":
            rsvp = EventRSVP.objects.filter(qr_registrasi_token=token).select_related("user", "event").first()
        else:
            rsvp = EventRSVP.objects.filter(qr_kupon_token=token).select_related("user", "event").first()

        if not rsvp:
            error = "Data RSVP tidak ditemukan."
        elif kind == "registrasi":
            if rsvp.status_kehadiran == "hadir":
                already = True
            else:
                rsvp.status_kehadiran = "hadir"
                rsvp.checked_in_at = timezone.now()
                rsvp.save(update_fields=["status_kehadiran", "checked_in_at"])
        elif kind == "kupon":
            if rsvp.status_kupon == "redeemed":
                already = True
            else:
                rsvp.status_kupon = "redeemed"
                rsvp.redeemed_at = timezone.now()
                rsvp.save(update_fields=["status_kupon", "redeemed_at"])

    context = {"error": error, "rsvp": rsvp, "kind": kind, "already": already}
    return render(request, "siwak/qr_verify.html", context)


@staff_member_required
def admin_scan(request):
    """Camera-based scanner UI for panitia (PRD 8 — Scan QR attendance / kupon)."""
    return render(request, "siwak/admin_scan.html", {})