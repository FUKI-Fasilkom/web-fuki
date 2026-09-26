from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import BirDep, PengurusInti


def team_list(request):
    """Halaman utama Our Team - menampilkan PI, KI, MDC, dan seluruh BirDep"""
    birdeps = BirDep.objects.filter(is_active=True).order_by('urutan', 'nama')

    context = {
        'birdeps': birdeps,
        'title': 'Our Team'
    }
    return render(request, 'birdep/team_list.html', context)

def pengurus_list(request, kategori='pi'):
    """Halaman daftar pengurus untuk kategori PI, KI, atau MDC.

    Daftar jabatan diambil dari database supaya perubahan struktur
    kepengurusan cukup dilakukan lewat admin, tanpa mengubah kode.
    """
    kategori_sah = dict(PengurusInti.KATEGORI_CHOICES)
    if kategori not in kategori_sah:
        raise Http404("Kategori pengurus tidak dikenal")

    pengurus_list = PengurusInti.objects.filter(
        kategori=kategori,
        is_active=True,
    ).order_by('urutan', 'nama')

    context = {
        'pengurus_list': pengurus_list,
        'kategori': kategori,
        'kategori_nama': kategori_sah[kategori],
        'title': kategori_sah[kategori],
    }
    return render(request, 'birdep/pi_list.html', context)


def pi_detail(request, slug):
    """Halaman detail satu orang pengurus"""
    pengurus = get_object_or_404(PengurusInti, slug=slug, is_active=True)

    context = {
        'pengurus': pengurus,
        'title': pengurus.jabatan,
    }
    return render(request, 'birdep/pi_detail.html', context)


def _halaman_birdep(request, slug, tab, **konteks):
    """Satu tab halaman BirDep (Tentang / Program / Fungsionaris).

    `konteks` berisi fungsi `birdep -> queryset` untuk daftar yang hanya dimiliki
    tab itu, supaya ketiga tab tetap satu kerangka.
    """
    birdep = get_object_or_404(BirDep, slug=slug, is_active=True)
    context = {
        'birdep': birdep,
        'title': f'{birdep.nama_panjang} - {tab.capitalize()}',
        'current_tab': tab,
    }
    context.update({nama: ambil(birdep) for nama, ambil in konteks.items()})
    return render(request, f'birdep/birdep_{tab}.html', context)


def birdep_tentang(request, slug):
    """Halaman detail tentang BirDep"""
    return _halaman_birdep(request, slug, 'tentang')


def birdep_program(request, slug):
    """Halaman program dari BirDep"""
    return _halaman_birdep(
        request, slug, 'program',
        programs=lambda b: b.programs.filter(is_active=True).order_by('urutan', 'judul'),
    )


def birdep_fungsionaris(request, slug):
    """Halaman fungsionaris dari BirDep"""
    return _halaman_birdep(
        request, slug, 'fungsionaris',
        fungsionaris_list=lambda b: b.fungsionaris_set.filter(is_active=True).order_by('urutan', 'nama'),
    )
