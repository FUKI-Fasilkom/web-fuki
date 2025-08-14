from django.shortcuts import render
from .models import Kegiatan
from datetime import datetime

def kegiatan_all(request):
    kegiatan_list = Kegiatan.objects.all().order_by('tanggal')
    return render(request, 'kegiatan_all.html', {'kegiatan_list': kegiatan_list})

def kegiatan_upcoming(request):
    kegiatan_list = Kegiatan.objects.filter(tanggal__gte=datetime.now()).order_by('tanggal')
    return render(request, 'kegiatan_upcoming.html', {'kegiatan_list': kegiatan_list})

def kegiatan_past(request):
    kegiatan_list = Kegiatan.objects.filter(tanggal__lt=datetime.now()).order_by('-tanggal')
    return render(request, 'kegiatan_past.html', {'kegiatan_list': kegiatan_list})
