from django.shortcuts import render
from django.http import JsonResponse

def health_check(request):
    return JsonResponse({"status": "ok"})

def beranda(request):
    # Beranda dilayani dari dua URL ("/" dan "/beranda"). canonical_path menyatakan
    # ke Google bahwa "/" adalah versi resminya, supaya keduanya tidak dihitung
    # sebagai dua halaman yang saling menggerus peringkat.
    return render(request, 'beranda.html', {'canonical_path': '/'})

def hubungi_kami(request):
    return render(request, 'hubungi_kami.html')
