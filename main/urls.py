from django.urls import path
from .views import beranda, health_check
from .views import hubungi_kami, lapor, lapor_submit

urlpatterns = [
    path('', beranda, name='beranda'),
    path('beranda', beranda, name='beranda'),
    path('hubungi_kami', hubungi_kami, name='hubungi_kami'),
    path('lapor', lapor, name='lapor'),
    path('lapor/submit', lapor_submit, name='lapor_submit'),
    path('health/', health_check),
]
