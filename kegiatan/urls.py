from django.urls import path
from .views import kegiatan_all, kegiatan_upcoming, kegiatan_past

app_name = 'kegiatan'

urlpatterns = [
    path('', kegiatan_all, name='kegiatan_all'),
    path('upcoming/', kegiatan_upcoming, name='kegiatan_upcoming'),
    path('past/', kegiatan_past, name='kegiatan_past'),
]