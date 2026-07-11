from django.urls import path
from .views import *

app_name = 'kegiatan'

urlpatterns = [
    path('', kegiatan_upcoming_page, name='home'),
    path('all/', kegiatan_all_page, name='kegiatan_all'),
    path('upcoming/', kegiatan_upcoming_page, name='kegiatan_upcoming'),
    path('past/', kegiatan_past_page, name='kegiatan_past'),
]