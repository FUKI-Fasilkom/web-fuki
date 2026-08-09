# birdep/views.py
from django.http import Http404
from django.shortcuts import render, get_object_or_404
from .models import BirDep, Program, Fungsionaris, PengurusInti

def team_list(request):
    """Halaman utama Our Team - menampilkan PI, KI, MDC, dan seluruh BirDep"""
    birdeps = BirDep.objects.filter(is_active=True).order_by('nama')

    context = {
        'birdeps': birdeps,
        'title': 'Our Team'
    }
    return render(request, 'birdep/team_list.html', context)

def pengurus_list(request, kategori='pi'):
    """Halaman daftar pengurus untuk kategori PI, KI, atau MDC.

    Sebelumnya daftar jabatan ditulis langsung di dalam view. Sekarang diambil
    dari database supaya perubahan struktur kepengurusan cukup dilakukan lewat
    admin, tanpa mengubah kode.
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

def birdep_tentang(request, slug):
    """Halaman detail tentang BirDep"""
    birdep = get_object_or_404(BirDep, slug=slug, is_active=True)
    
    context = {
        'birdep': birdep,
        'title': f'{birdep.nama_panjang} - Tentang',
        'current_tab': 'tentang'
    }
    return render(request, 'birdep/birdep_tentang.html', context)

def birdep_program(request, slug):
    """Halaman program dari BirDep"""
    birdep = get_object_or_404(BirDep, slug=slug, is_active=True)
    programs = Program.objects.filter(
        birdep=birdep, 
        is_active=True
    ).order_by('urutan', 'judul')
    
    context = {
        'birdep': birdep,
        'programs': programs,
        'title': f'{birdep.nama_panjang} - Program',
        'current_tab': 'program'
    }
    return render(request, 'birdep/birdep_program.html', context)

def birdep_fungsionaris(request, slug):
    """Halaman fungsionaris dari BirDep"""
    birdep = get_object_or_404(BirDep, slug=slug, is_active=True)
    fungsionaris_list = Fungsionaris.objects.filter(
        birdep=birdep, 
        is_active=True
    ).order_by('urutan', 'nama')
    
    context = {
        'birdep': birdep,
        'fungsionaris_list': fungsionaris_list,
        'title': f'{birdep.nama_panjang} - Fungsionaris',
        'current_tab': 'fungsionaris'
    }
    return render(request, 'birdep/birdep_fungsionaris.html', context)