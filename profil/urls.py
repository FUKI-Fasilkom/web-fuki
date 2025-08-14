from django.urls import path
from . import views

urlpatterns = [
    path('', views.tentang_fuki, name='profil'),
]