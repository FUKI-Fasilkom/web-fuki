from django.urls import path

from .views import (
    birdep_fungsionaris,
    birdep_program,
    birdep_tentang,
    pengurus_list,
    pi_detail,
    team_list,
)

app_name = 'birdep'

urlpatterns = [
    # Halaman utama Our Team
    path('', team_list, name='team_list'),  # /team/

    # Daftar pengurus non-BirDep: PI, KI, dan MDC.
    # Ketiganya memakai view yang sama, dibedakan lewat parameter kategori.
    path('pi/', pengurus_list, {'kategori': 'pi'}, name='pi_list'),      # /team/pi/
    path('ki/', pengurus_list, {'kategori': 'ki'}, name='ki_list'),      # /team/ki/
    path('mdc/', pengurus_list, {'kategori': 'mdc'}, name='mdc_list'),   # /team/mdc/

    # Detail satu pengurus. Diletakkan sebelum pola <slug:slug> di bawah
    # supaya /team/pengurus/... tidak tertangkap sebagai slug BirDep.
    path('pengurus/<slug:slug>/', pi_detail, name='pi_detail'),

    # Halaman BirDep
    path('<slug:slug>/', birdep_tentang, name='birdep_detail'),
    path('<slug:slug>/tentang/', birdep_tentang, name='birdep_tentang'),
    path('<slug:slug>/program/', birdep_program, name='birdep_program'),
    path('<slug:slug>/fungsionaris/', birdep_fungsionaris, name='birdep_fungsionaris'),
]
