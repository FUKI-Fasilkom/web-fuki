# birdep/views.py
from django.shortcuts import render, get_object_or_404
from .models import BirDep, Program, Fungsionaris, PengurusInti

def team_list(request):
    """Halaman utama Our Team - menampilkan PI, KI, dan BirDep lainnya"""
    birdeps = BirDep.objects.filter(is_active=True).order_by('nama')
    
    context = {
        'birdeps': birdeps,
        'title': 'Our Team'
    }
    return render(request, 'birdep/team_list.html', context)

def pi_list(request):
    """Halaman list Pengurus Inti"""
    # Data hardcode sesuai screenshot
    jabatan_list = [
        {'nama': 'Dewan Pertimbangan', 'slug': 'dewan-pertimbangan'},
        {'nama': 'Ketua', 'slug': 'ketua'},
        {'nama': 'Wakil Ketua', 'slug': 'wakil-ketua'},
        {'nama': 'Sekretaris', 'slug': 'sekretaris'},
        {'nama': 'Bendahara', 'slug': 'bendahara'},
        {'nama': 'Koordinator Bidang Internal', 'slug': 'koordinator-bidang-internal'},
        {'nama': 'Koordinator Bidang Syiar', 'slug': 'koordinator-bidang-syiar'},
        {'nama': 'Koordinator Bidang Pembinaan dan Kaderisasi', 'slug': 'koordinator-bidang-pembinaan-kaderisasi'},
        {'nama': 'Koordinator Bidang Keuumatan', 'slug': 'koordinator-bidang-keuumatan'},
        {'nama': 'Koordinator Bidang Bisnis dan Teknologi', 'slug': 'koordinator-bidang-bisnis-teknologi'},
        {'nama': 'Koordinator Bidang Eksternal', 'slug': 'koordinator-bidang-eksternal'},
    ]
    
    context = {
        'jabatan_list': jabatan_list,
        'title': 'Pengurus Inti'
    }
    return render(request, 'birdep/pi_list.html', context)

def pi_detail(request, slug):
    """Halaman detail Pengurus Inti berdasarkan jabatan"""
    pengurus = get_object_or_404(PengurusInti, slug=slug, is_active=True)
    
    context = {
        'pengurus': pengurus,
        'title': f'{pengurus.get_jabatan_display()}',
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