from django.shortcuts import render

def beranda(request):
    return render(request, 'beranda.html')

def hubungi_kami(request):
    return render(request, 'hubungi_kami.html')
