from django.urls import path
from .views import team_list, pi_list, pi_detail, birdep_tentang, birdep_program, birdep_fungsionaris

app_name = 'birdep'

urlpatterns = [
    # Team URLs (menggantikan birdep)
    path('', team_list, name='team_list'),  # /team/
    
    # PI URLs
    path('pi/', pi_list, name='pi_list'),  # /team/pi/
    path('pi/<slug:slug>/', pi_detail, name='pi_detail'),  # /team/pi/ketua/
    
    # BirDep URLs (untuk KI dan lainnya)
    path('<slug:slug>/', birdep_tentang, name='birdep_detail'),  # /team/ki/
    path('<slug:slug>/tentang/', birdep_tentang, name='birdep_tentang'),  # /team/ki/tentang/
    path('<slug:slug>/program/', birdep_program, name='birdep_program'),  # /team/ki/program/
    path('<slug:slug>/fungsionaris/', birdep_fungsionaris, name='birdep_fungsionaris'),  # /team/ki/fungsionaris/
]