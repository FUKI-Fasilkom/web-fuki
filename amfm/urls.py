from django.urls import path

from . import views, panel_views

app_name = "amfm"

urlpatterns = [
    path("admin/login/", panel_views.LoginAdminView.as_view(), name="panel_login"),
    path("admin/", panel_views.panel_beranda, name="panel_beranda"),
    path("admin/pendaftar/", panel_views.panel_daftar, name="panel_daftar"),
    path("admin/pendaftar/status-massal/", panel_views.panel_massal, name="panel_massal"),
    path("admin/pendaftar/<int:pk>/", panel_views.panel_detail, name="panel_detail"),
    path("admin/pendaftar/<int:pk>/keputusan/", panel_views.panel_keputusan, name="panel_keputusan"),
    path("admin/pendaftar/<int:pk>/bukti/", panel_views.panel_bukti, name="panel_bukti"),
    path("admin/pendaftar/<int:pk>/bukti/<int:nomor>/", panel_views.panel_bukti, name="panel_bukti_nomor"),
    path("admin/pendaftar/<int:pk>/hapus/", panel_views.panel_hapus, name="panel_hapus"),
    path("admin/pengaturan/", panel_views.panel_pengaturan, name="panel_pengaturan"),
    path("admin/konten/", panel_views.panel_konten, name="panel_konten"),
    path("admin/konten/<slug:slug>/", panel_views.panel_konten_daftar, name="panel_konten_daftar"),
    path("admin/konten/<slug:slug>/tambah/", panel_views.panel_konten_form, name="panel_konten_tambah"),
    path("admin/konten/<slug:slug>/<int:pk>/ubah/", panel_views.panel_konten_form, name="panel_konten_ubah"),
    path("admin/konten/<slug:slug>/<int:pk>/hapus/", panel_views.panel_konten_hapus, name="panel_konten_hapus"),
    path("", views.beranda, name="beranda"),
    path("daftar/bukti/<int:nomor>/", views.bukti_peserta, name="bukti_peserta"),
    path("daftar/", views.daftar, name="daftar"),
    path("masuk-sso/", views.masuk_sso, name="masuk_sso"),  
]
