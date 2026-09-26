import calendar as pycal
import logging
import re
import unicodedata

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .akses import AksesDitolak, mentee_required, pemindai_required
from .forms import CariKelompokForm, RSVPForm, TugasAnswerForm
from .models import (
    EventRSVP,
    FAQMentoring,
    GaleriFoto,
    KetuaSiwak,
    MentoringBenefit,
    MentoringTujuan,
    Profile,
    SistemMentoring,
    SiwakEvent,
    SiwakInfo,
    TimelineEvent,
    Tugas,
    TugasSubmission,
)
from .services.pemindai import boleh_memindai, jenis_pindai
from .services.qrcode_service import (
    kupon_qr_data_uri,
    registrasi_qr_data_uri,
    unsign_payload,
)
from .signals import delete_unused_tugas_file

logger = logging.getLogger(__name__)


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
        # Menaik, menimpa Meta.ordering `-tahun`: judulnya "dari Tahun ke Tahun",
        # jadi kartunya harus terbaca maju dari kiri ke kanan. Sengaja di sini,
        # bukan di Meta, supaya daftar panel tetap menaruh yang terbaru di atas.
        "ketua_list": KetuaSiwak.objects.order_by("tahun"),
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
        identitas = form.cleaned_data["nama_lengkap"].strip()
        mentee = Profile.objects.filter(role=Profile.ROLE_MENTEE).select_related("kelompok")
        # NPM unik, nama tidak — tanpa jurusan sebagai pembeda, cocokkan NPM lebih dulu
        # supaya dua mentee dengan nama sama tidak tertukar.
        peserta = (
            mentee.filter(npm__iexact=identitas).first()
            or mentee.filter(nama_lengkap__iexact=identitas).order_by("pk").first()
        )

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

# Palet penanda tugas di kalender, selaras tema SIWAK (navy/emas) dan cukup kontras dengan teks putih.
CALENDAR_COLORS = [
    "#001B3D", "#A77A1F", "#0048A3", "#8B1E15",
    "#1F7A6D", "#6B3FA0", "#C25E12", "#5C7A29",
]


@mentee_required
def tugas_list(request):
    tugas_qs = Tugas.objects.filter(is_active=True)
    rows = []
    tasks_by_date = {}
    now = timezone.now()

    for index, tugas in enumerate(tugas_qs):
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

        # Satu warna per tugas (dipakai kalender & legenda); dipakai ulang bila tugas > palet.
        deadline = timezone.localtime(tugas.deadline)
        tasks_by_date.setdefault(deadline.date(), []).append({
            "pk": tugas.pk,
            "judul": tugas.judul_tugas,
            "color": CALENDAR_COLORS[index % len(CALENDAR_COLORS)],
            "status": status,
            "overdue": not submission and now > tugas.deadline,
            "deadline": deadline,
        })

    today = timezone.localdate()

    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month

    cal = pycal.Calendar(firstweekday=6)  # Sunday-first, like the Figma calendar
    weeks = [
        [
            {
                "date": day,
                "in_month": day.month == month,
                "is_today": day == today,
                "tasks": tasks_by_date.get(day, []),
            }
            for day in week
        ]
        for week in cal.monthdatescalendar(year, month)
    ]
    # Legenda: tugas yang jatuh tempo pada bulan yang sedang ditampilkan.
    month_tasks = sorted(
        (task for day in tasks_by_date for task in tasks_by_date[day]
         if (day.year, day.month) == (year, month)),
        key=lambda task: task["deadline"],
    )

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
        "month_tasks": month_tasks,
        "today": today,
        "is_current_month": (year, month) == (today.year, today.month),
        "today_year": today.year,
        "today_month": today.month,
        "prev_year": prev_year,
        "prev_month": prev_m,
        "next_year": next_year,
        "next_month": next_m,
    }

    return render(request, "siwak/tugas_list.html", context)


@mentee_required
@require_http_methods(["GET", "POST"])
def tugas_detail(request, pk):
    tugas = get_object_or_404(Tugas, pk=pk, is_active=True)
    uploaded_files = []
    try:
        with transaction.atomic():
            profiles = Profile.objects.filter(
                user=request.user, role=Profile.ROLE_MENTEE
            )
            if request.method == "POST":
                # Kunci profil juga menserialkan dua pengumpulan pertama sekaligus.
                profiles = profiles.select_for_update()
            # Tanpa select_related: `kelompok` nullable, dan Postgres menolak
            # SELECT ... FOR UPDATE pada sisi outer join. Diambil lazy saat rename.
            profile = profiles.first()
            if not profile:
                # Role-nya dicabut di sela pengecekan decorator dan kunci ini.
                raise AksesDitolak("mentee")

            submission = tugas.submission_for(request.user)
            is_past_deadline = timezone.now() > tugas.deadline
            if request.method == "POST" and submission and is_past_deadline:
                messages.error(request, "Submission tidak dapat diubah setelah deadline.")
                return redirect("siwak:tugas_detail", pk=pk)

            data = request.POST if request.method == "POST" else None
            files = request.FILES if request.method == "POST" else None
            form = TugasAnswerForm(data, files, tugas=tugas, submission=submission)
            if request.method == "POST":
                # Tanpa pertanyaan tidak ada yang bisa dikumpulkan.
                if not form.fields:
                    return redirect("siwak:tugas_detail", pk=pk)
                if form.is_valid():
                    if submission is None:
                        submission = TugasSubmission(tugas=tugas, user=request.user)
                    submission.save()

                    for question in tugas.questions.all():
                        value = form.cleaned_data[f"question_{question.pk}"]
                        # Hanya upload baru yang di-rename; file lama (bukan UploadedFile) dibiarkan.
                        if question.tipe == "file" and isinstance(value, UploadedFile):
                            value.name = _nama_berkas_tugas(tugas, profile, question, value.name)
                        answer, _ = submission.answers.get_or_create(question=question)
                        answer.text_answer = value if question.tipe == "text" else ""
                        answer.selected_choice_id = value if question.tipe == "choice" else None
                        answer.file_answer = value if question.tipe == "file" else None
                        _save_tugas_upload(answer, "file_answer", uploaded_files)

                    messages.success(request, "Tugas berhasil dikirim.")
                    return redirect("siwak:tugas_detail", pk=pk)
    except Exception:
        # Storage tidak ikut rollback DB. Bersihkan hanya upload baru yang gagal.
        for storage, name in uploaded_files:
            try:
                delete_unused_tugas_file(storage, name, "default")
            except Exception:
                logger.exception("Gagal membersihkan upload tugas %s", name)
        raise

    # Jawaban terurut per pertanyaan: dipakai tampilan read-only setelah deadline
    # dan untuk menautkan berkas lama pada form edit sebelum deadline.
    answers = (
        list(
            submission.answers.select_related("question", "selected_choice")
            .order_by("question__urutan", "question_id")
        )
        if submission else []
    )
    answer_by_field = {f"question_{a.question_id}": a for a in answers}

    context = {
        "tugas": tugas,
        "submission": submission,
        "assignment_review": (
            getattr(submission, "mentor_review", None) if submission else None
        ),
        "answers": answers,
        "form_rows": [
            {"field": field, "answer": answer_by_field.get(field.name)}
            for field in form
        ],
        "is_past_deadline": is_past_deadline,
        # Submission terkunci (read-only) hanya setelah deadline; sebelumnya bebas diedit.
        "is_locked": bool(submission and is_past_deadline),
        "form": form,
        "can_submit": bool(form.fields) and not (submission and is_past_deadline),
    }

    return render(request, "siwak/tugas_detail.html", context)


def _bersihkan_bagian_nama(teks, batas):
    """ASCII saja, spasi/simbol jadi '-', dipotong `batas` (kolom FileField cuma 100 karakter)."""
    teks = unicodedata.normalize("NFKD", teks or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", teks).strip("-")[:batas].strip("-")


def _nama_berkas_tugas(tugas, profile, question, nama_asli):
    """<namaTugas>_q<idPertanyaan>_<namaKelompok>_<namaMentee>_<NPM>.<ext>, dipakai sebelum upload ke S3.

    id pertanyaan selalu disertakan supaya dua file dari pertanyaan berbeda pada
    tugas yang sama tidak bernama sama. Bagian variabel dipotong agar NPM (pembeda
    utama) tidak terpotong oleh batas panjang path FileField.
    """
    ext = nama_asli.rsplit(".", 1)[-1].lower() if "." in nama_asli else ""
    kelompok = profile.kelompok.nama_kelompok if profile.kelompok else "tanpa-kelompok"
    bagian = [
        _bersihkan_bagian_nama(tugas.judul_tugas, 18) or "tugas",
        f"q{question.pk}",
        _bersihkan_bagian_nama(kelompok, 12) or "kelompok",
        _bersihkan_bagian_nama(profile.nama_lengkap, 20) or "mentee",
        _bersihkan_bagian_nama(profile.npm, 20) or "npm",
    ]
    nama = "_".join(bagian)
    return f"{nama}.{ext}" if ext else nama


def _save_tugas_upload(instance, field_name, uploaded_files):
    file = getattr(instance, field_name)
    is_new_upload = file and not file._committed
    try:
        instance.save()
    finally:
        file = getattr(instance, field_name)
        if is_new_upload and file._committed:
            uploaded_files.append((file.storage, file.name))

# ---------------------------------------------------------------------------
# 5.2 / 6 — RSVP + QR Registrasi Ulang & QR Kupon Makan
# ---------------------------------------------------------------------------

@login_required
def rsvp_event(request, id):
    # Event yang RSVP-nya sudah ditutup menampilkan halaman "RSVP ditutup",
    # kecuali user sudah pernah RSVP — mereka tetap bisa melihat QR-nya.
    event = get_object_or_404(SiwakEvent, id=id)
    rsvp = EventRSVP.objects.filter(event=event, user=request.user).first()
    if not event.rsvp_dibuka and not rsvp:
        return render(request, "siwak/rsvp.html", {
            "event": event,
            "rsvp_ditutup": True,
            "back_url": reverse("siwak:landing"),
        })

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
    field = EventRSVP.JENIS_QR[kind].field_token
    qs = EventRSVP.objects.filter(**{field: token}).select_related("user", "event")
    if lock:
        qs = qs.select_for_update()
    return qs.first()


@pemindai_required
@require_http_methods(["GET", "POST"])
def qr_verify(request, signed):
    """Scanned-QR landing page (PRD 6.1/6.2). Superusers and scanner accounts.

    A scanner account only passes for the QR kind it holds a permission for:
    the gatekeeper can't redeem a kupon, the konsumsi desk can't check anyone
    in. That check runs before the RSVP row is even looked up.

    GET is read-only: it only renders a *confirmation* page. The actual
    check-in / kupon redemption happens on a CSRF-protected POST, so a passive
    ``<img src=".../qr/...">`` load in an admin's browser can't flip
    attendance state. The POST runs inside a transaction with
    ``SELECT ... FOR UPDATE`` on the RSVP row, so two concurrent scans can't
    both succeed (TOCTOU).
    """
    # Yang sampai di sini selalu boleh memindai, jadi "kembali" berarti kembali
    # ke halaman pemindai, siap untuk QR berikutnya.
    context = {"back_url": reverse("siwak:pindai_beranda")}

    try:
        payload = unsign_payload(signed)
    except signing.SignatureExpired:
        context["error"] = "QR sudah kedaluwarsa."
        return render(request, "siwak/qr_verify.html", context)
    except signing.BadSignature:
        context["error"] = "QR tidak valid atau rusak."
        return render(request, "siwak/qr_verify.html", context)
    kind, token = payload["kind"], payload["token"]

    if not boleh_memindai(request.user, kind):
        # Halaman galat yang sama dengan QR rusak, bukan 403 polos: panitia di
        # meja registrasi yang salah menerima QR kupon perlu tahu apa yang
        # terjadi, bukan hanya melihat "Forbidden".
        bisa = " dan ".join(EventRSVP.LABEL_PINDAI[k] for k in jenis_pindai(request.user))
        context["error_judul"] = "Akses Ditolak"
        context["error"] = (
            f"Ini {EventRSVP.LABEL_PINDAI.get(kind, 'QR jenis lain')}. "
            f"Akun ini hanya bisa memindai {bisa}."
        )
        return render(request, "siwak/qr_verify.html", context, status=403)

    error = None
    already = False
    with transaction.atomic():
        # POST mengubah status, jadi barisnya dikunci supaya pindaian yang
        # bersamaan berjalan bergantian.
        rsvp = _find_rsvp(kind, token, lock=request.method == "POST")
        if rsvp is None:
            error = "Data RSVP tidak ditemukan."
        else:
            already = rsvp.qr_terpakai(kind)
            if request.method == "POST" and not already:
                if kind == "registrasi" and rsvp.kehadiran != "hadir":
                    error = "Check-in ditolak: kehadiran RSVP peserta bukan 'hadir'."
                else:
                    rsvp.ubah_status_qr(kind, EventRSVP.JENIS_QR[kind].status_terpakai)

    context.update({
        "error": error,
        "rsvp": rsvp,
        "kind": kind,
        "already": already,
        "confirm": request.method == "GET" and rsvp is not None and not already,
    })
    return render(request, "siwak/qr_verify.html", context)


@pemindai_required
def pindai_beranda(request):
    """Halaman awal akun pemindai QR, tujuannya setelah Login Akun Khusus.

    Tidak ada pemindai di dalam halaman ini: produksi masih HTTP, dan browser
    hanya mengizinkan kamera di HTTPS. Pemindaiannya dilakukan kamera HP, yang
    membuka link QR peserta di browser bawaan — halaman ini menjelaskan itu,
    dan menyebut jenis QR yang boleh dipindai akun ini.

    Di bawahnya daftar acara seperti "SIWAK Events" di panel, tapi hanya
    dengan tombol RSVP: panitia tidak mengubah, menghapus, atau membuka-tutup
    RSVP acara — itu tetap urusan pengurus.
    """
    return render(request, "siwak/pindai.html", {
        "jenis": [EventRSVP.LABEL_PINDAI[k] for k in jenis_pindai(request.user)],
        "events": SiwakEvent.objects.annotate(jumlah_rsvp=Count("rsvp_list")),
        "back_url": reverse("siwak:landing"),
    })
