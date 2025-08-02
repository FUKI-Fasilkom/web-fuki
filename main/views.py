from django.shortcuts import render

def beranda(request):
    return render(request, 'beranda.html')
