from django.shortcuts import render

from .forms import CariKelompokForm
from .models import (
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
)


# ---------------------------------------------------------------------------
# 4.1 / 4.2 — Public informational page (landing) & timeline
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


# ---------------------------------------------------------------------------
# 4.3 — Informasi Kelompok Mentoring (Cari Kelompok)
# ---------------------------------------------------------------------------

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