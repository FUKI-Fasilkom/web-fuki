from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from .models import Kajian


def blog_kajian_page(request):
    query = request.GET.get('q')
    # Model sudah terurut dari yang terbaru (Meta.ordering = ['-tanggal']).
    kajian_list = Kajian.objects.all()
    if query:
        kajian_list = kajian_list.filter(
            Q(judul__icontains=query) | Q(penceramah__icontains=query)
        )
    return render(request, 'blog_kajian.html', {'kajian_list': kajian_list})


def kajian_detail(request, id):
    article = get_object_or_404(Kajian, id=id)
    # Sidebar: 4 kajian terbaru selain yang sedang dibaca.
    sidebar_list = Kajian.objects.exclude(id=id)[:4]
    return render(request, 'kajian_detail.html', {
        'article': article,
        'sidebar_list': sidebar_list,
    })
