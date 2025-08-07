from django.urls import path
from .views import beranda
from .views import hubungi_kami

urlpatterns = [
    path('', beranda, name='beranda'),
    path('beranda', beranda, name='beranda'),
    path('hubungi_kami', hubungi_kami, name='hubungi_kami')
]