"""Halaman 403 "Akses Ditolak" bersama (siwak/akses.py).

User yang sudah login tapi membuka bagian SIWAK milik peran lain mendapat satu
halaman bergaya SIWAK — bukan 403 polos — yang menyebut halaman mana yang
tertutup dan menawarkan jalan ke bagian miliknya sendiri. Status HTTP tetap 403.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from .models import EventRSVP, KelompokMentoring, Profile, SiwakInfo
from .sso import role_landing_url

User = get_user_model()

PANEL = reverse("siwak:panel_beranda")
MENTOR = reverse("siwak:mentor_dashboard")
PINDAI = reverse("siwak:pindai_beranda")
TUGAS = reverse("siwak:tugas_list")


class AksesDitolakTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staf = User.objects.create_user(username="staf", is_staff=True)
        cls.mentor = User.objects.create_user(username="mentor-andi")
        Profile.objects.create(
            user=cls.mentor, role=Profile.ROLE_MENTOR, nama_lengkap="Andi",
            kelompok=KelompokMentoring.objects.create(nama_kelompok="Kelompok 1"),
        )
        cls.mentee = User.objects.create_user(username="mentee")
        Profile.objects.create(user=cls.mentee, npm="2500000001", role=Profile.ROLE_MENTEE)
        cls.panitia = User.objects.create_user(
            username=f"{EventRSVP.USERNAME_PEMINDAI_PREFIX}gate"
        )
        app_label, codename = EventRSVP.IZIN_PINDAI["registrasi"].split(".")
        cls.panitia.user_permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
        cls.tanpa_peran = User.objects.create_user(username="tanpa-peran")

    def _tolak(self, user, url, halaman, tujuan_url, tujuan_label):
        self.client.force_login(user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "siwak/akses_ditolak.html")
        self.assertTemplateUsed(response, "components/redesign_header.html")
        self.assertContains(
            response, f"Anda tidak memiliki akses ke halaman {halaman}.", status_code=403
        )
        self.assertContains(response, f'href="{tujuan_url}"', status_code=403)
        self.assertContains(response, tujuan_label, status_code=403)
        return response

    def test_mentor_opening_the_admin_panel_is_sent_to_the_mentor_portal(self):
        self._tolak(self.mentor, PANEL, "Admin Panel SIWAK", MENTOR, "Pergi ke Portal Mentor")

    def test_staff_opening_the_mentor_portal_is_sent_to_the_admin_panel(self):
        self._tolak(self.staf, MENTOR, "Mentor", PANEL, "Pergi ke Admin Panel")

    def test_every_mentor_page_uses_it(self):
        for name in ("mentor_attendance", "mentor_assessments", "mentor_task_reviews"):
            with self.subTest(name=name):
                self._tolak(self.staf, reverse(f"siwak:{name}"), "Mentor", PANEL,
                            "Pergi ke Admin Panel")

    def test_mentee_opening_the_mentor_portal_is_sent_to_tugas(self):
        self._tolak(self.mentee, MENTOR, "Mentor", TUGAS, "Pergi ke Tugas Mentoring")

    def test_committee_account_opening_the_panel_is_sent_to_the_scanner(self):
        self._tolak(self.panitia, PANEL, "Admin Panel SIWAK", PINDAI, "Pergi ke Pemindai QR")

    def test_mentor_opening_the_scanner_is_sent_to_the_mentor_portal(self):
        self._tolak(self.mentor, PINDAI, "Pemindai QR", MENTOR, "Pergi ke Portal Mentor")

    def test_staff_opening_the_scanner_is_sent_to_the_admin_panel(self):
        self._tolak(self.staf, PINDAI, "Pemindai QR", PANEL, "Pergi ke Admin Panel")

    def test_staff_opening_tugas_is_sent_to_the_admin_panel(self):
        self._tolak(self.staf, TUGAS, "Tugas Mentoring", PANEL, "Pergi ke Admin Panel")

    def test_user_without_a_role_is_sent_back_to_siwak(self):
        response = self._tolak(self.tanpa_peran, PANEL, "Admin Panel SIWAK",
                               reverse("siwak:landing"), "Kembali ke SIWAK-NG")
        self.assertNotContains(response, "Pergi ke", status_code=403)

    def test_the_offered_destination_is_where_login_would_land(self):
        """Tombolnya dan tujuan setelah login berasal dari satu aturan yang sama."""
        for user in (self.staf, self.mentor, self.mentee, self.panitia):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                url = PINDAI if user != self.panitia else PANEL
                self.assertContains(
                    self.client.get(url), f'href="{role_landing_url(user)}"', status_code=403
                )

    def test_it_names_the_account_and_offers_logout_and_the_cp(self):
        SiwakInfo.objects.update_or_create(pk=SiwakInfo.get_solo().pk,
                                           defaults={"kontak_cp": "https://wa.me/620000"})
        self.client.force_login(self.mentor)
        response = self.client.get(PANEL)
        self.assertContains(response, "mentor-andi", status_code=403)
        self.assertContains(response, f'href="{reverse("siwak:logout")}"', status_code=403)
        self.assertContains(response, 'href="https://wa.me/620000"', status_code=403)

    def test_other_permission_errors_get_a_generic_message(self):
        """PermissionDenied biasa (di sini: pengurus menyimpan catatan privat)
        memakai halaman yang sama, tanpa membocorkan teks exception-nya."""
        mentee = Profile.objects.get(user=self.mentee)
        self.client.force_login(self.staf)
        response = self.client.post(
            reverse("siwak:mentee_catatan", args=[mentee.pk]), {"notes": "x"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "siwak/akses_ditolak.html")
        self.assertContains(response, "Anda tidak memiliki akses ke halaman ini.", status_code=403)
        self.assertNotContains(response, "hanya bisa diubah", status_code=403)
        self.assertContains(response, "Pergi ke Admin Panel", status_code=403)

    def test_a_wrong_role_visit_is_logged_without_a_traceback(self):
        self.client.force_login(self.mentor)
        with self.assertLogs("django.request", level="WARNING") as log:
            self.client.get(PANEL)
        self.assertEqual(len(log.records), 1)
        self.assertIsNone(log.records[0].exc_info)

    def test_anonymous_visitors_are_still_sent_to_log_in(self):
        for url in (PANEL, PINDAI, MENTOR):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response.url)
