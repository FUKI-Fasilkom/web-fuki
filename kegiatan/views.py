from django.shortcuts import render
from .models import Kegiatan
from django.template import loader
from django.http import HttpResponse
import datetime

today = datetime.date.today()

def kegiatan_all_page(request):
    kegiatan_upcoming = Kegiatan.objects.filter(tanggal__gte=today).order_by('tanggal')
    kegiatan_past = Kegiatan.objects.filter(tanggal__lt=today).order_by('-tanggal')
    template = loader.get_template("kegiatan_list.html")
    context = {
        'kegiatan_upcoming': kegiatan_upcoming,
        'kegiatan_past': kegiatan_past,
        'active_tab': 'all',
    }
    return HttpResponse(template.render(context, request))

def kegiatan_upcoming_page(request):
    kegiatan_upcoming = Kegiatan.objects.filter(tanggal__gte=today).order_by('tanggal')
    template = loader.get_template("kegiatan_list.html")
    context = {
        'kegiatan_upcoming': kegiatan_upcoming,
        'active_tab': 'upcoming',
    }
    return HttpResponse(template.render(context, request))

def kegiatan_past_page(request):
    kegiatan_past = Kegiatan.objects.filter(tanggal__lt=today).order_by('-tanggal')
    template = loader.get_template("kegiatan_list.html")
    context = {
        'kegiatan_past': kegiatan_past,
        'active_tab': 'past',
    }
    return HttpResponse(template.render(context, request))
