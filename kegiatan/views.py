from django.shortcuts import render
from .models import Kegiatan
from datetime import datetime
from django.template import loader
from django.http import HttpResponse

def kegiatan_all(request):
    kegiatan_list = Kegiatan.objects.all()
    template = loader.get_template("kegiatan_all.html")
    context = {
        'kegiatan_list': kegiatan_list,
    }
    return HttpResponse(template.render(context, request))


def kegiatan_upcoming(request):
    kegiatan_list = Kegiatan.objects.all()
    template = loader.get_template("kegiatan_upcoming.html")
    context = {
        'kegiatan_list': kegiatan_list,
    }
    return HttpResponse(template.render(context, request))

def kegiatan_past(request):
    kegiatan_list = Kegiatan.objects.all()
    template = loader.get_template("kegiatan_past.html")
    context = {
        'kegiatan_list': kegiatan_list,
    }
    return HttpResponse(template.render(context, request))
