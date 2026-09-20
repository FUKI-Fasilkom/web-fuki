from django_cas_ng import views as cas_views
from django.urls import path

from . import mentor_views, panel_views, views


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
    path("feedback/", mentor_views.mentee_feedback_history, name="mentee_feedback_history"),
    path(
        "submission/<int:submission_id>/download/",
        mentor_views.submission_download,
        name="submission_download",
    ),

    # 6 — Mentor Page. Pembuatan MentoringSession belum diekspos sampai
    # kepemilikan prosesnya disepakati dengan divisi terkait.
    path("mentor/", mentor_views.mentor_dashboard, name="mentor_dashboard"),
    path(
        "mentor/mentee/<int:participant_id>/",
        mentor_views.mentee_detail,
        name="mentor_mentee_detail",
    ),
    path(
        "mentor/kelompok/<int:group_id>/tugas/",
        mentor_views.assignments,
        name="mentor_assignments",
    ),
    # 5.2 / 6 — RSVP & QR
    path("rsvp/<int:id>/", views.rsvp_event, name="rsvp"),
    path("qr/<str:signed>/", views.qr_verify, name="qr_verify"),

    # 8 — Panel pengelola SIWAK (khusus pengurus)
    path("admin/", panel_views.panel_beranda, name="panel_beranda"),
    path("admin/bagian/<slug:bagian>/", panel_views.panel_bagian, name="panel_bagian"),
    path("admin/info/", panel_views.panel_info, name="panel_info"),
    path("admin/acara/<int:pk>/rsvp/", panel_views.panel_rsvp, name="panel_rsvp"),
    path("admin/acara/<int:pk>/rsvp/csv/", panel_views.panel_rsvp_csv, name="panel_rsvp_csv"),
    path("admin/acara/<int:pk>/rsvp/buka-tutup/", panel_views.panel_rsvp_toggle, name="panel_rsvp_toggle"),
    path("admin/rsvp/<int:pk>/status/", panel_views.panel_rsvp_status, name="panel_rsvp_status"),
    path("admin/rsvp/<int:pk>/hapus/", panel_views.panel_rsvp_hapus, name="panel_rsvp_hapus"),
    path("admin/data/<slug:slug>/", panel_views.panel_daftar, name="panel_daftar"),
    path("admin/data/<slug:slug>/tambah/", panel_views.panel_tambah, name="panel_tambah"),
    path("admin/data/<slug:slug>/<int:pk>/ubah/", panel_views.panel_ubah, name="panel_ubah"),
    path("admin/data/<slug:slug>/<int:pk>/hapus/", panel_views.panel_hapus, name="panel_hapus"),

    # Penyusun pertanyaan tugas & pemeriksa jawabannya
    path("admin/sesi/<int:pk>/aktif/", panel_views.panel_sesi_aktif, name="panel_sesi_aktif"),
    path("admin/tugas/<int:pk>/pertanyaan/", panel_views.panel_pertanyaan, name="panel_pertanyaan"),
    path(
        "admin/tugas/<int:pk>/pertanyaan/tambah/",
        panel_views.panel_pertanyaan_tambah,
        name="panel_pertanyaan_tambah",
    ),
    path("admin/pertanyaan/<int:pk>/ubah/", panel_views.panel_pertanyaan_ubah, name="panel_pertanyaan_ubah"),
    path("admin/pertanyaan/<int:pk>/hapus/", panel_views.panel_pertanyaan_hapus, name="panel_pertanyaan_hapus"),
    path("admin/pertanyaan/<int:pk>/urut/", panel_views.panel_pertanyaan_urut, name="panel_pertanyaan_urut"),
    path("admin/tugas/<int:pk>/jawaban/", panel_views.panel_jawaban, name="panel_jawaban"),
    path("admin/tugas/<int:pk>/jawaban/csv/", panel_views.panel_jawaban_csv, name="panel_jawaban_csv"),

    # Penyunting relasi yang dipanggil dropdown di halaman daftar
    # `pk` adalah MahasiswaProfile — dipakai baik untuk mentee maupun mentor.
    path("admin/peserta/<int:pk>/kelompok/", panel_views.panel_set_kelompok, name="panel_set_kelompok"),
]
