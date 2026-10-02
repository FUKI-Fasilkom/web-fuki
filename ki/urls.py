from django.urls import path

from . import panel_views

app_name = "ki"

# Tanpa slug jenis data seperti panel SIWAK: panel ini cuma punya satu menu,
# jadi /ki/admin/ langsung daftar Kegiatan.
urlpatterns = [
    path("admin/", panel_views.panel_daftar, name="panel_daftar"),
    path("admin/tambah/", panel_views.panel_tambah, name="panel_tambah"),
    path("admin/<int:pk>/ubah/", panel_views.panel_ubah, name="panel_ubah"),
    path("admin/<int:pk>/hapus/", panel_views.panel_hapus, name="panel_hapus"),
]
