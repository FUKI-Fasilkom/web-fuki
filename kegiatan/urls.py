from django.urls import path
from .views import kegiatan_detail, kegiatan_ics, kegiatan_page

app_name = 'kegiatan'

urlpatterns = [
    path('', kegiatan_page, name='home'),
    path('<int:id>/', kegiatan_detail, name='detail'),
    path('<int:id>/kalender.ics', kegiatan_ics, name='ics'),
]
