from django.urls import path
from .views import kegiatan_page

app_name = 'kegiatan'

urlpatterns = [
    path('', kegiatan_page, name='home'),
]
