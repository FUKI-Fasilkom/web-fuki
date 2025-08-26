from django.urls import path
from .views import *

app_name = 'kegiatan'

urlpatterns = [
    path('', kegiatan_all, name='home'),
    path('all/', kegiatan_all, name='kegiatan_all'),
    path('upcoming/', kegiatan_upcoming, name='kegiatan_upcoming'),
    path('past/', kegiatan_past, name='kegiatan_past'),
]