from django.shortcuts import render

from .models import AmfmBenefit, AmfmInfo, AmfmTimeline


def beranda(request):
    """Halaman informasi AM-FM (PRD 4.1), mengikuti design Figma AM-FM.

    `url_daftar` sengaja belum dikirim: formulir pendaftaran (PRD 4.2) belum
    ada, jadi kedua tombol "Daftar Sekarang" tampil nonaktif ("Segera Dibuka").
    Begitu formulirnya ada, cukup isi `url_daftar` di sini.
    """
    context = {
        "info": AmfmInfo.get_solo(),
        "benefit_list": AmfmBenefit.objects.all(),
        "timeline_list": AmfmTimeline.objects.filter(is_active=True),
    }
    return render(request, "amfm/beranda.html", context)
