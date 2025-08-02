from django.urls import path
from .views import beranda

urlpatterns = [
    path('', beranda, name='beranda'),
]