"""Mentor non-SSO harus bisa memakai semua yang bisa dipakai mentor SSO.

Akun lokal berbeda dari akun SSO di dua hal: `npm` kosong (NULL) dan
`auth_source="lokal"`. Semua fitur mentor dijaga lewat `role`, jadi mestinya
tidak peduli asal akun, tapi ada satu tempat yang dulu diam-diam mengandaikan
NPM: form RSVP (`npm` wajib terisi, padahal mentor lokal tidak punya).

Cara paling murah menjaga kesetaraan itu: menjalankan ulang seluruh suite mentor
yang sudah ada dengan mentornya diganti akun lokal. Fitur mentor baru otomatis
ikut teruji untuk kedua jenis akun tanpa perlu menulis tes dua kali.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from . import test_mentor, test_mentor_rekap
from .models import EventRSVP, KelompokMentoring, Profile, SiwakEvent
from .services.qrcode_service import registrasi_qr_data_uri, sign_payload


User = get_user_model()


def jadikan_lokal(profil):
    """Ubah `profil` (mentor) jadi mentor non-SSO, persis seperti bentukan panel."""
    profil.npm = None
    profil.jurusan = ""
    profil.angkatan = ""
    profil.auth_source = Profile.SOURCE_LOKAL
    profil.save()
    akun = profil.user
    akun.username = f"{Profile.USERNAME_LOKAL_PREFIX}{profil.pk}"
    akun.save(update_fields=["username"])
    return profil


class MentorFeatureLokalTests(test_mentor.MentorFeatureTests):
    """Seluruh MentorFeatureTests, tapi kedua mentornya akun lokal."""

    def setUp(self):
        super().setUp()
        jadikan_lokal(self.mentor)
        jadikan_lokal(self.other_mentor)

    def test_the_mentors_really_are_local_accounts(self):
        for mentor in (self.mentor, self.other_mentor):
            mentor.refresh_from_db()
            self.assertIsNone(mentor.npm)
            self.assertTrue(mentor.is_akun_lokal)

    # Dua tes induk menguji jalur klaim/login ulang SSO lewat NPM. Akun lokal
    # tidak punya NPM dan CAS menolaknya sengaja (lihat MentorLokalTests), jadi
    # skenarionya memang tidak berlaku untuk mereka.
    def test_prepared_mentor_profile_is_claimed_by_sso_login_and_stays_mentor(self):
        self.skipTest("Klaim SSO lewat NPM tidak berlaku untuk mentor non-SSO.")

    def test_relogin_does_not_demote_mentor_or_move_their_group(self):
        self.skipTest("Login ulang SSO tidak berlaku untuk mentor non-SSO.")


class MentorRekapPagesLokalTests(test_mentor_rekap.MentorRekapPagesTests):
    """Presensi, Nilai Mentee, dan Feedback Tugas dengan mentor akun lokal."""

    def setUp(self):
        super().setUp()
        jadikan_lokal(self.mentor)
        jadikan_lokal(self.other_mentor)


class RsvpMentorLokalTests(TestCase):
    """Halaman RSVP untuk mentor non-SSO (dulu ditolak karena NPM-nya kosong)."""

    def setUp(self):
        self.kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")
        self.akun = User.objects.create_user(username="mentor-rahma", password="RahasiaKuat123")
        self.mentor = Profile.objects.create(
            user=self.akun,
            nama_lengkap="Kak Rahma",
            role=Profile.ROLE_MENTOR,
            auth_source=Profile.SOURCE_LOKAL,
            kelompok=self.kelompok,
        )
        self.event = SiwakEvent.objects.create(judul="Mentoring #1", rsvp_dibuka=True)
        self.url = reverse("siwak:rsvp", args=[self.event.id])
        self.client.force_login(self.akun)

    def test_the_form_renders_with_the_name_and_no_sso_label_on_a_missing_npm(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kak Rahma")
        # Tanpa NPM tidak ada yang "otomatis dari SSO" untuk ditampilkan.
        self.assertContains(response, "Tidak ada NPM")
        self.assertNotContains(response, "Otomatis dari SSO")

    def test_an_sso_user_still_sees_the_sso_labels(self):
        akun = User.objects.create_user(username="2506534245")
        Profile.objects.create(user=akun, npm="2506534245", nama_lengkap="Fiqhi", jurusan="IK")
        self.client.force_login(akun)

        response = self.client.get(self.url)

        self.assertContains(response, "Otomatis dari SSO")
        self.assertContains(response, "2506534245")
        self.assertNotContains(response, "Tidak ada NPM")

    def test_a_local_mentor_can_rsvp_hadir_and_gets_both_qr(self):
        response = self.client.post(self.url, {"kehadiran": "hadir", "npm": ""})

        self.assertRedirects(response, self.url)
        rsvp = EventRSVP.objects.get(event=self.event, user=self.akun)
        self.assertEqual(rsvp.kehadiran, "hadir")
        self.assertEqual(rsvp.status_kehadiran, "belum_hadir")
        self.assertTrue(rsvp.qr_registrasi_token)
        self.assertTrue(rsvp.qr_kupon_token)

        halaman = self.client.get(self.url)
        self.assertIn("qr_registrasi", halaman.context)
        self.assertIn("qr_kupon", halaman.context)

    def test_the_qr_is_the_same_kind_a_web_rsvp_gets(self):
        self.client.post(self.url, {"kehadiran": "hadir"})
        rsvp = EventRSVP.objects.get(event=self.event, user=self.akun)

        halaman = self.client.get(self.url)

        self.assertEqual(halaman.context["qr_registrasi"], registrasi_qr_data_uri(halaman.wsgi_request, rsvp))

    def test_izin_needs_a_reason_and_is_saved_with_one(self):
        kosong = self.client.post(self.url, {"kehadiran": "izin", "alasan_izin": ""})
        self.assertEqual(kosong.status_code, 200)
        self.assertContains(kosong, "Alasan izin wajib diisi")
        self.assertFalse(EventRSVP.objects.filter(event=self.event).exists())

        ada = self.client.post(self.url, {"kehadiran": "izin", "alasan_izin": "Acara keluarga"})
        self.assertEqual(ada.status_code, 302)
        rsvp = EventRSVP.objects.get(event=self.event, user=self.akun)
        self.assertEqual((rsvp.kehadiran, rsvp.alasan_izin), ("izin", "Acara keluarga"))

    def test_a_second_post_does_not_create_a_second_rsvp(self):
        self.client.post(self.url, {"kehadiran": "hadir"})
        self.client.post(self.url, {"kehadiran": "tidak_hadir"})

        rsvp = EventRSVP.objects.get(event=self.event, user=self.akun)
        self.assertEqual(rsvp.kehadiran, "hadir")

    def test_a_closed_event_still_refuses_a_new_rsvp(self):
        self.event.rsvp_dibuka = False
        self.event.save()

        response = self.client.post(self.url, {"kehadiran": "hadir"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(EventRSVP.objects.filter(event=self.event).exists())

    def test_two_local_mentors_can_both_rsvp(self):
        """Dua NULL di kolom NPM tidak boleh saling menabrak."""
        akun2 = User.objects.create_user(username="mentor-dina", password="RahasiaKuat123")
        Profile.objects.create(
            user=akun2, nama_lengkap="Kak Dina", role=Profile.ROLE_MENTOR,
            auth_source=Profile.SOURCE_LOKAL,
        )
        self.client.post(self.url, {"kehadiran": "hadir"})
        self.client.force_login(akun2)
        self.client.post(self.url, {"kehadiran": "hadir"})

        self.assertEqual(EventRSVP.objects.filter(event=self.event).count(), 2)

    def test_the_rsvp_shows_up_for_staff_and_at_the_scanner_without_an_npm(self):
        self.client.post(self.url, {"kehadiran": "hadir"})
        rsvp = EventRSVP.objects.get(event=self.event, user=self.akun)
        staf = User.objects.create_superuser(username="admin", password="x")
        self.client.force_login(staf)

        panel = self.client.get(reverse("siwak:panel_rsvp", args=[self.event.pk]))
        self.assertContains(panel, "Kak Rahma")

        pindai = self.client.get(
            reverse("siwak:qr_verify", args=[sign_payload("registrasi", rsvp.qr_registrasi_token)])
        )
        self.assertEqual(pindai.status_code, 200)
        self.assertContains(pindai, "Kak Rahma")

    def test_the_login_round_trip_reaches_the_rsvp_page(self):
        """Anonim → halaman RSVP → login lokal → kembali ke RSVP (deep link)."""
        self.client.logout()
        masuk = self.client.get(self.url)
        self.assertEqual(masuk.status_code, 302)

        hasil = self.client.post(
            reverse("siwak:login_khusus") + f"?next={self.url}",
            {"username": "mentor-rahma", "password": "RahasiaKuat123"},
        )
        self.assertRedirects(hasil, self.url, fetch_redirect_response=False)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_the_local_mentor_sees_mentor_links_in_the_navbar(self):
        response = self.client.get(reverse("siwak:landing"))

        self.assertContains(response, reverse("siwak:mentor_dashboard"))

    def test_staff_can_create_an_rsvp_for_a_local_mentor_from_the_panel(self):
        staf = User.objects.create_user(username="pengurus", is_staff=True)
        self.client.force_login(staf)

        response = self.client.post(
            reverse("siwak:panel_profil_rsvp", args=[self.mentor.pk]),
            {"event": self.event.pk, "kehadiran": "hadir"},
        )

        self.assertEqual(response.status_code, 302)
        rsvp = EventRSVP.objects.get(event=self.event, user=self.akun)
        self.assertEqual(rsvp.kehadiran, "hadir")
