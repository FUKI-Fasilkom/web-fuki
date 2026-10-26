from django.urls import path

from . import views

app_name = "amfm"

urlpatterns = [
    path("", views.beranda, name="beranda"),
]
