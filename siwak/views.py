from django.shortcuts import render

from .models import (
    FAQMentoring,
    GaleriFoto,
    KetuaSiwak,
    MentoringBenefit,
    MentoringTujuan,
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