from django.urls import path

from . import views

app_name = "siwak"

urlpatterns = [
    # 4.1 / 4.2 — Public: landing & timeline
    path("", views.landing, name="landing"),
    # 4.3 — Cari Kelompok
    path("kelompok/", views.kelompok_search, name="kelompok_search"),
    # 7 — Authentication (dev-mode; lihat siwak/sso.py)
    path("login/", views.maba_login, name="login"),
    path("logout/", views.maba_logout, name="logout"),
    # 5.1 — Tugas
    path("tugas/", views.tugas_list, name="tugas_list"),
    path("tugas/<int:pk>/", views.tugas_detail, name="tugas_detail"),
]