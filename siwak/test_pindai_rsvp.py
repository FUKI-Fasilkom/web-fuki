"""Daftar RSVP untuk akun panitia di /siwak/pindai/.

Panitia melihat daftar acara dengan hanya tombol RSVP, lalu daftar RSVP yang
sama dengan panel — tanpa ubah acara, hapus RSVP, buka-tutup RSVP, dan CSV —
dan hanya boleh membetulkan status QR yang jenisnya boleh dia pindai.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from .models import EventRSVP, KelompokMentoring, Profile, SiwakEvent

User = get_user_model()


def _akun_panitia(username, *jenis):
    akun = User.objects.create_user(username=f"{EventRSVP.USERNAME_PEMINDAI_PREFIX}{username}")
    for kind in jenis:
        app_label, codename = EventRSVP.IZIN_PINDAI[kind].split(".")
        akun.user_permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    return akun


class PindaiRsvpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.gatekeeper = _akun_panitia("gate", "registrasi")
        cls.konsumsi = _akun_panitia("makan", "kupon")
        cls.keduanya = _akun_panitia("dua", "registrasi", "kupon")
        cls.event = SiwakEvent.objects.create(judul="Main Event", lokasi="Balairung")
        cls.kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 7")
        maba = User.objects.create_user(username="maba")
        Profile.objects.create(
            user=maba, npm="2500000001", nama_lengkap="Ani Maba",
            role=Profile.ROLE_MENTEE, kelompok=cls.kelompok,
        )
        cls.rsvp = EventRSVP.objects.create(
            event=cls.event, user=maba, kehadiran="izin", alasan_izin="Sakit",
        )
        cls.url_beranda = reverse("siwak:pindai_beranda")
        cls.url_daftar = reverse("siwak:pindai_rsvp", args=[cls.event.pk])
        cls.url_status = reverse("siwak:pindai_rsvp_status", args=[cls.rsvp.pk])

    def ubah(self, medan, nilai):
        return self.client.post(self.url_status, {
            "medan": medan, "nilai": nilai, "next": f"{self.url_daftar}?q=Ani",
        })

    # --- Halaman pemindai: daftar acara ------------------------------------

    def test_scanner_home_lists_events_with_only_an_rsvp_button(self):
        self.client.force_login(self.gatekeeper)
        response = self.client.get(self.url_beranda)
        self.assertContains(response, "Main Event")
        self.assertContains(response, f'href="{self.url_daftar}"')
        self.assertContains(response, "RSVP (1)")
        for url in (
            reverse("siwak:panel_ubah", args=["event", self.event.pk]),
            reverse("siwak:panel_hapus", args=["event", self.event.pk]),
            reverse("siwak:panel_rsvp_toggle", args=[self.event.pk]),
            reverse("siwak:panel_rsvp", args=[self.event.pk]),
        ):
            self.assertNotContains(response, url)

    # --- Daftar RSVP panitia -----------------------------------------------

    def test_the_rsvp_list_shows_participants_without_admin_actions(self):
        self.client.force_login(self.keduanya)
        response = self.client.get(self.url_daftar)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "siwak/pindai_rsvp.html")
        self.assertTemplateNotUsed(response, "siwak/panel/base.html")
        self.assertContains(response, "Ani Maba")
        self.assertContains(response, "2500000001")
        self.assertContains(response, "Alasan izin: Sakit")
        self.assertContains(response, "Kelompok 7")  # saringan kelompok ikut
        for teks in (
            reverse("siwak:panel_rsvp_hapus", args=[self.rsvp.pk]),
            reverse("siwak:panel_rsvp_csv", args=[self.event.pk]),
            reverse("siwak:panel_ubah", args=["event", self.event.pk]),
            reverse("siwak:panel_rsvp_toggle", args=[self.event.pk]),
            reverse("siwak:panel_rsvp_status", args=[self.rsvp.pk]),
            "Ubah acara", "Unduh CSV",
        ):
            self.assertNotContains(response, teks)
        # Menu samping panel tidak ikut.
        self.assertNotContains(response, reverse("siwak:panel_beranda"))

    def test_both_dropdowns_for_an_account_that_may_scan_both(self):
        self.client.force_login(self.keduanya)
        response = self.client.get(self.url_daftar)
        self.assertContains(response, f'action="{self.url_status}"', count=2)
        self.assertContains(response, 'value="kehadiran"')
        self.assertContains(response, 'value="kupon"')

    def test_gatekeeper_only_gets_the_attendance_dropdown(self):
        self.client.force_login(self.gatekeeper)
        response = self.client.get(self.url_daftar)
        self.assertContains(response, f'action="{self.url_status}"', count=1)
        self.assertContains(response, 'value="kehadiran"')
        self.assertNotContains(response, 'name="medan" value="kupon"')
        self.assertContains(response, "Unused")  # kupon tetap terlihat, hanya dibaca

    def test_konsumsi_only_gets_the_kupon_dropdown(self):
        self.client.force_login(self.konsumsi)
        response = self.client.get(self.url_daftar)
        self.assertContains(response, f'action="{self.url_status}"', count=1)
        self.assertContains(response, 'name="medan" value="kupon"')
        self.assertNotContains(response, 'name="medan" value="kehadiran"')

    def test_search_and_group_filters_stay_on_the_scanner_page(self):
        self.client.force_login(self.gatekeeper)
        response = self.client.get(self.url_daftar, {"q": "tidak-ada"})
        self.assertContains(response, "Tidak ada peserta")
        self.assertContains(response, f'href="{self.url_daftar}"')
        response = self.client.get(self.url_daftar, {"kelompok": self.kelompok.pk})
        self.assertContains(response, "Ani Maba")

    # --- Mengubah status ----------------------------------------------------

    def test_gatekeeper_checks_a_participant_in_manually(self):
        self.client.force_login(self.gatekeeper)
        response = self.ubah("kehadiran", "hadir")
        self.assertRedirects(response, f"{self.url_daftar}?q=Ani", fetch_redirect_response=False)
        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status_kehadiran, "hadir")
        self.assertIsNotNone(self.rsvp.checked_in_at)

        self.ubah("kehadiran", "belum_hadir")
        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status_kehadiran, "belum_hadir")
        self.assertIsNone(self.rsvp.checked_in_at)

    def test_konsumsi_redeems_a_kupon_manually(self):
        self.client.force_login(self.konsumsi)
        self.ubah("kupon", "redeemed")
        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status_kupon, "redeemed")
        self.assertIsNotNone(self.rsvp.redeemed_at)

    def test_an_account_cannot_change_a_qr_kind_it_may_not_scan(self):
        for akun, medan, nilai in (
            (self.gatekeeper, "kupon", "redeemed"),
            (self.konsumsi, "kehadiran", "hadir"),
        ):
            with self.subTest(akun=akun.username):
                self.client.force_login(akun)
                self.assertEqual(self.ubah(medan, nilai).status_code, 403)
        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status_kehadiran, "belum_hadir")
        self.assertEqual(self.rsvp.status_kupon, "unused")

    def test_unknown_values_are_rejected_without_saving(self):
        self.client.force_login(self.keduanya)
        self.ubah("kehadiran", "entah")
        self.ubah("rahasia", "hadir")
        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status_kehadiran, "belum_hadir")

    def test_status_change_is_post_only(self):
        self.client.force_login(self.keduanya)
        self.assertEqual(self.client.get(self.url_status).status_code, 405)

    def test_an_unsafe_next_falls_back_to_the_scanner_list(self):
        self.client.force_login(self.gatekeeper)
        response = self.client.post(self.url_status, {
            "medan": "kehadiran", "nilai": "hadir", "next": "https://jahat.example.com/",
        })
        self.assertRedirects(response, self.url_daftar, fetch_redirect_response=False)

    # --- Siapa yang boleh masuk ---------------------------------------------

    def test_non_scanners_are_kept_out(self):
        mentor = User.objects.create_user(username="mentor-x")
        Profile.objects.create(user=mentor, role=Profile.ROLE_MENTOR)
        staf = User.objects.create_user(username="staf", is_staff=True)
        for akun in (mentor, staf):
            with self.subTest(akun=akun.username):
                self.client.force_login(akun)
                self.assertEqual(self.client.get(self.url_daftar).status_code, 403)
                self.assertEqual(self.ubah("kehadiran", "hadir").status_code, 403)
        self.client.logout()
        response = self.client.get(self.url_daftar)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("siwak:login_khusus"), response.url)
        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status_kehadiran, "belum_hadir")

    def test_superuser_may_use_it_with_both_dropdowns(self):
        self.client.force_login(User.objects.create_superuser(username="root", password="x"))
        response = self.client.get(self.url_daftar)
        self.assertContains(response, f'action="{self.url_status}"', count=2)

    def test_scanners_still_cannot_open_the_panel_rsvp_list(self):
        self.client.force_login(self.keduanya)
        self.assertEqual(
            self.client.get(reverse("siwak:panel_rsvp", args=[self.event.pk])).status_code, 403
        )
        response = self.client.post(
            reverse("siwak:panel_rsvp_hapus", args=[self.rsvp.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(EventRSVP.objects.filter(pk=self.rsvp.pk).exists())

    def test_panel_rsvp_list_keeps_all_its_admin_actions(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        response = self.client.get(reverse("siwak:panel_rsvp", args=[self.event.pk]))
        panel_status = reverse("siwak:panel_rsvp_status", args=[self.rsvp.pk])
        self.assertContains(response, f'action="{panel_status}"', count=2)
        self.assertContains(response, reverse("siwak:panel_rsvp_hapus", args=[self.rsvp.pk]))
        self.assertContains(response, "Ubah acara")
        self.assertContains(response, "Unduh CSV")
        self.assertNotContains(response, self.url_status)
