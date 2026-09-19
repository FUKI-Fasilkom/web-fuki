from django.urls import path

from . import views
from django_cas_ng import views as cas_views


app_name = "siwak"


urlpatterns = [
    # 4.1 / 4.2 / 4.3 — Public
    path("", views.landing, name="landing"),
    path("event/<int:pk>/", views.event_detail, name="event_detail"),
    path("kelompok/", views.kelompok_search, name="kelompok_search"),

    # 7 — Authentication (with sso ui cas2)
    path("sso-login/", cas_views.LoginView.as_view(), name="cas_ng_login"),
    path("sso-logout/", cas_views.LogoutView.as_view(), name="cas_ng_logout"),

    # 5.1 — Tugas
    path("tugas/", views.tugas_list, name="tugas_list"),
    path("tugas/<int:pk>/", views.tugas_detail, name="tugas_detail"),

    # 5.2 / 6 — RSVP & QR
    path("rsvp/<int:id>/", views.rsvp_event, name="rsvp"),
    path("qr/<str:signed>/", views.qr_verify, name="qr_verify"),
]