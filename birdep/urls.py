from django.urls import path
from .views import birdep_list, birdep_tentang, birdep_program, birdep_fungsionaris

app_name = 'birdep'

urlpatterns = [
    path('', birdep_list, name='birdep_list'),
    path('<slug:slug>/', birdep_tentang, name='birdep_detail'),
    path('<slug:slug>/tentang/', birdep_tentang, name='birdep_tentang'),
    path('<slug:slug>/program/', birdep_program, name='birdep_program'),
    path('<slug:slug>/fungsionaris/', birdep_fungsionaris, name='birdep_fungsionaris'),
]