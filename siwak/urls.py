from django.urls import path

from . import views

app_name = "siwak"

urlpatterns = [
    # 4.1 / 4.2 — Public: landing & timeline
    path("", views.landing, name="landing"),
]