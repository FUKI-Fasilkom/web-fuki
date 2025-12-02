from django.shortcuts import render, get_object_or_404
from .models import Kajian
from django.db.models import Q

def blog_kajian_page(request):
    # Logika Pencarian
    query = request.GET.get('q')
    
    # Default: Urutkan dari yang terbaru
    kajian_list = Kajian.objects.all().order_by('-tanggal')

    if query:
        # Filter berdasarkan judul atau penceramah
        kajian_list = kajian_list.filter(
            Q(judul__icontains=query) | 
            Q(penceramah__icontains=query)
        )

    context = {
        'kajian_list': kajian_list
    }
    return render(request, 'blog_kajian.html', context)

def kajian_detail(request, id):
    article = get_object_or_404(Kajian, id=id)
    
    # Sidebar Logic:
    # 1. exclude(id=id): Jangan tampilkan artikel yang sedang dibaca.
    # 2. order_by('-tanggal'): Urutkan dari tanggal terbaru (mendekati sekarang) ke terlama.
    # 3. [:4]: Ambil 4 item teratas.
    sidebar_list = Kajian.objects.exclude(id=id).order_by('-tanggal')[:4]

    context = {
        'article': article,
        'sidebar_list': sidebar_list
    }
    return render(request, 'kajian_detail.html', context)