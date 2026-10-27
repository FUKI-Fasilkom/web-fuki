from django.urls import path

from . import views

app_name = "amfm"

urlpatterns = [
    path("", views.beranda, name="beranda"),
    path("daftar/", views.daftar, name="daftar"),
    path("masuk-sso/", views.masuk_sso, name="masuk_sso"),
]
