from django.shortcuts import render
from .models import Fungsionaris

# Create your views here.

def tentang_fuki(request):
    fungsionaris_list = Fungsionaris.objects.all()
    return render(request, 'profil.html', {'fungsionaris_list': fungsionaris_list})
