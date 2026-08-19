from django.urls import path

from . import views

app_name = "siwak"

urlpatterns = [
    # 4.1 / 4.2 / 4.3 — Public
    path("", views.landing, name="landing"),
    path("kelompok/", views.kelompok_search, name="kelompok_search"),

    # 7 — Authentication (dev-mode; see siwak/sso.py)
    path("login/", views.maba_login, name="login"),
    path("logout/", views.maba_logout, name="logout"),

    # 5.1 — Tugas
    path("tugas/", views.tugas_list, name="tugas_list"),
    path("tugas/<int:pk>/", views.tugas_detail, name="tugas_detail"),

    # 5.2 / 6 — RSVP & QR
    path("rsvp/<str:tipe>/", views.rsvp_event, name="rsvp"),
    path("qr/<str:signed>/", views.qr_verify, name="qr_verify"),
    path("panitia/scan/", views.admin_scan, name="admin_scan"),
]