from django.shortcuts import render
from django.http import JsonResponse

def health_check(request):
    return JsonResponse({"status": "ok"})

def beranda(request):
    return render(request, 'beranda.html')

def hubungi_kami(request):
    return render(request, 'hubungi_kami.html')
