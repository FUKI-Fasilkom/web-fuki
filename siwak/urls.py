from django_cas_ng import views as cas_views
from django.urls import path
from django.views.generic import RedirectView

from . import auth_views, mentor_views, panel_views, sso, views


app_name = "siwak"


urlpatterns = [
    # 4.1 / 4.2 / 4.3 — Public
    path("", views.landing, name="landing"),
    path("event/<int:pk>/", views.event_detail, name="event_detail"),
    path("kelompok/", views.kelompok_search, name="kelompok_search"),

    # 7 — Authentication (sso ui cas2 + Akun Khusus: mentor non-SSO, pengurus,
    # pemindai QR)
    path("login/", auth_views.login_pilihan, name="login"),
    path("login/khusus/", auth_views.AkunKhususLoginView.as_view(), name="login_khusus"),
    # Alamat lama pintu yang dulu khusus mentor; mentor mungkin masih
    # menyimpannya. `next` ikut dibawa.
    path("login/mentor/", RedirectView.as_view(pattern_name="siwak:login_khusus", query_string=True)),
    path("logout/", auth_views.logout_cerdas, name="logout"),
    path("sso-login/", sso.RoleRedirectLoginView.as_view(), name="cas_ng_login"),
    path("sso-logout/", cas_views.LogoutView.as_view(), name="cas_ng_logout"),

    # 5.1 — Tugas
    path("tugas/", views.tugas_list, name="tugas_list"),
    path("tugas/<int:pk>/", views.tugas_detail, name="tugas_detail"),
    path("feedback/", mentor_views.mentee_feedback_history, name="mentee_feedback_history"),
    path(
        "submission/<int:submission_id>/answer/<int:answer_id>/download/",
        mentor_views.answer_download,
        name="answer_download",
    ),

    # 6 — Mentor Page. Pembuatan MentoringSession belum diekspos sampai
    # kepemilikan prosesnya disepakati dengan divisi terkait.
    path("mentor/", mentor_views.mentor_dashboard, name="mentor_dashboard"),
    path(
        "mentor/mentee/<int:participant_id>/",
        mentor_views.mentee_detail,
        name="mentor_mentee_detail",
    ),
    # Catatan privat mentee: satu pintu untuk mentor kelompoknya dan pengurus.
    path(
        "mentee/<int:participant_id>/catatan/",
        mentor_views.mentee_catatan,
        name="mentee_catatan",
    ),
    path(
        "mentor/kelompok/<int:group_id>/tugas/",
        mentor_views.assignments,
        name="mentor_assignments",
    ),
    path("mentor/presensi/", mentor_views.mentor_attendance, name="mentor_attendance"),
    path("mentor/nilai-mentee/", mentor_views.mentor_assessments, name="mentor_assessments"),
    path("mentor/penilaian-tugas/", mentor_views.mentor_task_reviews, name="mentor_task_reviews"),
    # 5.2 / 6 — RSVP & QR
    path("rsvp/<int:id>/", views.rsvp_event, name="rsvp"),
    path("qr/<str:signed>/", views.qr_verify, name="qr_verify"),
    path("pindai/", views.pindai_beranda, name="pindai_beranda"),

    # 8 — Panel pengelola SIWAK (khusus pengurus)
    path("admin/", panel_views.panel_beranda, name="panel_beranda"),
    path("admin/bagian/<slug:bagian>/", panel_views.panel_bagian, name="panel_bagian"),
    path("admin/info/", panel_views.panel_info, name="panel_info"),
    path("admin/kelompok/<int:pk>/", panel_views.panel_kelompok_detail, name="panel_kelompok_detail"),
    path("admin/mentee/<int:pk>/", panel_views.panel_mentee_detail, name="panel_mentee_detail"),
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
    # `pk` adalah Profile — dipakai baik untuk mentee maupun mentor.
    path("admin/peserta/<int:pk>/kelompok/", panel_views.panel_set_kelompok, name="panel_set_kelompok"),
    path("admin/profil/<int:pk>/role/", panel_views.panel_set_role, name="panel_set_role"),
    path("admin/profil/<int:pk>/npm/", panel_views.panel_set_npm, name="panel_set_npm"),
    path("admin/profil/<int:pk>/rsvp/", panel_views.panel_profil_rsvp, name="panel_profil_rsvp"),
    path("admin/kelompok/<int:pk>/link/", panel_views.panel_set_link, name="panel_set_link"),
]
