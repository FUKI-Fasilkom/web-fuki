from django.shortcuts import render, get_object_or_404
from django.http import Http404
from .models import BirDep, Program, Fungsionaris

def birdep_list(request):
    birdeps = BirDep.objects.filter(is_active=True).order_by('nama')
    
    context = {
        'birdeps': birdeps,
        'title': 'Biro & Departemen'
    }
    return render(request, 'birdep/birdep_list.html', context)

def birdep_tentang(request, slug):
    birdep = get_object_or_404(BirDep, slug=slug, is_active=True)
    
    context = {
        'birdep': birdep,
        'title': f'{birdep.nama} - Tentang',
        'current_tab': 'tentang'
    }
    return render(request, 'birdep/birdep_tentang.html', context)

def birdep_program(request, slug):
    birdep = get_object_or_404(BirDep, slug=slug, is_active=True)
    programs = Program.objects.filter(
        birdep=birdep, 
        is_active=True
    ).order_by('urutan', 'judul')
    
    context = {
        'birdep': birdep,
        'programs': programs,
        'title': f'{birdep.nama} - Program',
        'current_tab': 'program'
    }
    return render(request, 'birdep/birdep_program.html', context)

def birdep_fungsionaris(request, slug):
    birdep = get_object_or_404(BirDep, slug=slug, is_active=True)
    fungsionaris_list = Fungsionaris.objects.filter(
        birdep=birdep, 
        is_active=True
    ).order_by('urutan', 'nama')
    
    context = {
        'birdep': birdep,
        'fungsionaris_list': fungsionaris_list,
        'title': f'{birdep.nama} - Fungsionaris',
        'current_tab': 'fungsionaris'
    }
    return render(request, 'birdep/birdep_fungsionaris.html', context)