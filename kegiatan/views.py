from django.shortcuts import render
from .models import Kegiatan
from django.template import loader
from django.http import HttpResponse
import datetime

today = datetime.date.today()

def kegiatan_all_page(request):
    kegiatan_upcoming = Kegiatan.objects.filter(tanggal__gte=today).order_by('tanggal')
    kegiatan_past = Kegiatan.objects.filter(tanggal__lt=today).order_by('-tanggal')

    template = loader.get_template("kegiatan_all.html")
    context = {
        'kegiatan_upcoming': kegiatan_upcoming,
        'kegiatan_past': kegiatan_past,
    }
    return HttpResponse(template.render(context, request))


def kegiatan_upcoming_page(request):
    kegiatan_list = Kegiatan.objects.filter(tanggal__gte=today).order_by('tanggal')
    template = loader.get_template("kegiatan_upcoming.html")
    context = {
        'kegiatan_list': kegiatan_list,
    }
    return HttpResponse(template.render(context, request))

def kegiatan_past_page(request):
    kegiatan_list = Kegiatan.objects.filter(tanggal__lt=today).order_by('-tanggal')
    template = loader.get_template("kegiatan_past.html")
    context = {
        'kegiatan_list': kegiatan_list,
    }
    return HttpResponse(template.render(context, request))
