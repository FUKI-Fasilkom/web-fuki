import datetime

from django.http import JsonResponse
from django.shortcuts import render

from kegiatan.models import Kegiatan

from .models import Activity, CompanyProfile, Podcast, TentangFuki

def health_check(request):
    return JsonResponse({"status": "ok"})

def beranda(request):
    # Beranda dilayani dari dua URL ("/" dan "/beranda"). canonical_path menyatakan
    # ke Google bahwa "/" adalah versi resminya, supaya keduanya tidak dihitung
    # sebagai dua halaman yang saling menggerus peringkat.
    today = datetime.date.today()
    tentang = TentangFuki.get_solo()
    context = {
        'canonical_path': '/',
        'tentang': tentang,
        # Disaring di sini, bukan di dalam perulangan template: posisi tiap ubin
        # mosaik ditentukan forloop.counter, jadi baris tanpa berkas gambar harus
        # sudah hilang sebelum diulang agar susunannya tidak melenceng.
        'tentang_gambar': tentang.gambar_set.exclude(gambar='')[:5],
        # Dibatasi 6: tab kategori disaring di sisi klien, jadi semua kartu ikut
        # dirender sekaligus dan daftar panjang akan memberatkan halaman.
        'kegiatan_upcoming': Kegiatan.objects.filter(tanggal__gte=today)[:6],
        'kategori_choices': Kegiatan.KATEGORI_CHOICES,
        'activities': Activity.objects.filter(is_active=True),
        'podcasts': Podcast.objects.filter(is_active=True)[:3],
        'company_profiles': CompanyProfile.objects.filter(is_active=True)[:4],
    }
    return render(request, 'beranda.html', context)

def hubungi_kami(request):
    return render(request, 'hubungi_kami.html')
