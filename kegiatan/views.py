from django.shortcuts import render
from .models import Kegiatan
import datetime

def kegiatan_page(request):
    today = datetime.date.today()
    active_tab = request.GET.get('tab', 'all')
    
    kegiatan_upcoming = []
    kegiatan_past = []
    
    if active_tab in ['all', 'upcoming']:
        kegiatan_upcoming = Kegiatan.objects.filter(tanggal__gte=today).order_by('tanggal')
        
    if active_tab in ['all', 'past']:
        kegiatan_past = Kegiatan.objects.filter(tanggal__lt=today).order_by('-tanggal')
        
    context = {
        'kegiatan_upcoming': kegiatan_upcoming,
        'kegiatan_past': kegiatan_past,
        'active_tab': active_tab,
    }
    return render(request, "kegiatan_list.html", context)
