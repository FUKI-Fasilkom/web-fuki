"""Tombol "Buat RSVP" di daftar Profile/Mentee/Mentor panel: pengelola membuatkan RSVP."""

from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from .models import EventRSVP, KelompokMentoring, Profile, RSVPTertunda, SiwakEvent
from .services.qrcode_service import sign_payload, unsign_payload
from .sso import handle_cas_login
from .views import _find_rsvp

User = get_user_model()


def _pesan(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class PanelBuatRsvpTests(TestCase):
    def setUp(self):
        self.staf = User.objects.create_user(username="pengurus", is_staff=True)
        self.client.force_login(self.staf)
        self.event = SiwakEvent.objects.create(judul="Mentoring #1", rsvp_dibuka=False)
        self.akun = User.objects.create_user(username="fulan.satu")
        self.punya_akun = Profile.objects.create(
            user=self.akun, npm="2606000001", nama_lengkap="Fulan Satu", role=Profile.ROLE_MENTEE
        )
        self.tanpa_akun = Profile.objects.create(
            npm="2606000002", nama_lengkap="Fulan Dua", role=Profile.ROLE_MENTEE
        )
        self.url_akun = reverse("siwak:panel_profil_rsvp", args=[self.punya_akun.pk])
        self.url_tanpa = reverse("siwak:panel_profil_rsvp", args=[self.tanpa_akun.pk])

    def kirim(self, url, **data):
        data.setdefault("event", self.event.pk)
        data.setdefault("kehadiran", "hadir")
        return self.client.post(url, data)

    # --- tombol di daftar ------------------------------------------------

    def test_button_is_on_every_profile_based_list_and_carries_the_list_address(self):
        lokal = User.objects.create_user(username="mentor-ahmad")
        Profile.objects.create(
            user=lokal, nama_lengkap="Kak Ahmad", role=Profile.ROLE_MENTOR,
            auth_source=Profile.SOURCE_LOKAL,
        )
        Profile.objects.create(npm="2106000001", nama_lengkap="Kak Budi", role=Profile.ROLE_MENTOR)
        for slug in ("profil", "peserta", "mentor", "mentor_lokal"):
            with self.subTest(slug=slug):
                url = reverse("siwak:panel_daftar", args=[slug]) + "?urut=nama"
                response = self.client.get(url)
                baris = response.context["baris"]
                self.assertTrue(baris)
                for item in baris:
                    aksi = item["aksi"][0]
                    self.assertEqual(aksi["label"], "Buat RSVP")
                    self.assertEqual(
                        aksi["url"], reverse("siwak:panel_profil_rsvp", args=[item["pk"]])
                    )
                self.assertContains(response, f"?next={quote(url, safe='/')}")
                self.assertContains(response, "Buat RSVP")

    def test_other_lists_do_not_get_the_button(self):
        KelompokMentoring.objects.create(nama_kelompok="I-1")
        response = self.client.get(reverse("siwak:panel_daftar", args=["kelompok"]))
        self.assertNotContains(response, "Buat RSVP")

    # --- akses ------------------------------------------------------------

    def test_anonymous_is_sent_to_login_and_non_staff_is_forbidden(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url_akun).status_code, 302)
        self.assertEqual(self.kirim(self.url_akun).status_code, 302)

        self.client.force_login(User.objects.create_user(username="biasa"))
        self.assertEqual(self.client.get(self.url_akun).status_code, 403)
        self.assertEqual(self.kirim(self.url_akun).status_code, 403)
        self.assertEqual(EventRSVP.objects.count() + RSVPTertunda.objects.count(), 0)

    def test_unknown_profile_is_404(self):
        self.assertEqual(
            self.client.get(reverse("siwak:panel_profil_rsvp", args=[99999])).status_code, 404
        )

    # --- profil yang sudah punya akun ------------------------------------------

    def test_the_form_page_shows_events_and_current_state(self):
        response = self.client.get(self.url_akun)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fulan Satu")
        self.assertContains(response, "Belum RSVP")
        self.assertNotContains(response, "Belum punya akun login")

    def test_creating_an_rsvp_for_a_profile_with_an_account(self):
        response = self.kirim(self.url_akun)

        self.assertRedirects(
            response, reverse("siwak:panel_daftar", args=["profil"]), fetch_redirect_response=False
        )
        rsvp = EventRSVP.objects.get()
        self.assertEqual((rsvp.user, rsvp.event, rsvp.kehadiran, rsvp.alasan_izin),
                         (self.akun, self.event, "hadir", ""))
        self.assertEqual((rsvp.status_kehadiran, rsvp.status_kupon), ("belum_hadir", "unused"))
        self.assertRegex(rsvp.qr_registrasi_token, r"^[0-9a-f]{32}$")
        self.assertNotEqual(rsvp.qr_registrasi_token, rsvp.qr_kupon_token)
        self.assertIn("RSVP Fulan Satu untuk Mentoring #1 dibuat.", _pesan(response))

    def test_the_created_rsvp_shows_both_qr_codes_to_that_person_even_if_rsvp_is_closed(self):
        self.kirim(self.url_akun)
        rsvp = EventRSVP.objects.get()

        self.client.force_login(self.akun)
        response = self.client.get(reverse("siwak:rsvp", args=[self.event.id]))

        self.assertContains(response, "QR Kehadiran")
        self.assertContains(response, "QR Kupon Makan")
        for kind, token in (("registrasi", rsvp.qr_registrasi_token), ("kupon", rsvp.qr_kupon_token)):
            payload = unsign_payload(sign_payload(kind, token))
            self.assertEqual(_find_rsvp(payload["kind"], payload["token"]), rsvp)

    def test_after_saving_the_admin_goes_back_to_the_list_they_came_from(self):
        tujuan = reverse("siwak:panel_daftar", args=["peserta"]) + "?q=Fulan&page=2"
        response = self.client.post(
            self.url_akun, {"event": self.event.pk, "kehadiran": "hadir", "next": tujuan}
        )
        self.assertRedirects(response, tujuan, fetch_redirect_response=False)

    def test_an_external_next_address_is_ignored(self):
        response = self.client.post(
            self.url_akun,
            {"event": self.event.pk, "kehadiran": "hadir", "next": "https://evil.example/x"},
        )
        self.assertRedirects(
            response, reverse("siwak:panel_daftar", args=["profil"]), fetch_redirect_response=False
        )
        page = self.client.get(self.url_akun + "?next=https://evil.example/x")
        self.assertNotContains(page, "evil.example")

    def test_izin_needs_a_reason_and_stores_it(self):
        gagal = self.kirim(self.url_akun, kehadiran="izin", alasan_izin="  ")
        self.assertEqual(gagal.status_code, 200)
        self.assertContains(gagal, "Alasan izin wajib diisi")
        self.assertEqual(EventRSVP.objects.count(), 0)

        self.kirim(self.url_akun, kehadiran="izin", alasan_izin=" acara keluarga ")
        rsvp = EventRSVP.objects.get()
        self.assertEqual((rsvp.kehadiran, rsvp.alasan_izin), ("izin", "acara keluarga"))

    def test_the_reason_is_dropped_for_other_answers(self):
        self.kirim(self.url_akun, kehadiran="hadir", alasan_izin="tidak relevan")
        self.assertEqual(EventRSVP.objects.get().alasan_izin, "")

    def test_tidak_hadir_is_accepted(self):
        self.kirim(self.url_akun, kehadiran="tidak_hadir")
        self.assertEqual(EventRSVP.objects.get().kehadiran, "tidak_hadir")

    def test_invalid_answer_or_event_creates_nothing(self):
        self.assertEqual(self.kirim(self.url_akun, kehadiran="mungkin").status_code, 200)
        self.assertEqual(self.kirim(self.url_akun, event=99999).status_code, 200)
        self.assertEqual(EventRSVP.objects.count(), 0)

    def test_an_existing_rsvp_is_never_overwritten(self):
        awal = EventRSVP.objects.create(event=self.event, user=self.akun, kehadiran="izin", alasan_izin="x")
        EventRSVP.objects.filter(pk=awal.pk).update(status_kehadiran="hadir")

        response = self.kirim(self.url_akun, kehadiran="hadir")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "sudah punya RSVP untuk Mentoring #1")
        lagi = EventRSVP.objects.get()
        self.assertEqual((lagi.pk, lagi.kehadiran, lagi.status_kehadiran), (awal.pk, "izin", "hadir"))
        self.assertContains(self.client.get(self.url_akun), "Sudah RSVP · Izin")

    def test_a_second_event_can_still_be_added(self):
        EventRSVP.objects.create(event=self.event, user=self.akun)
        lain = SiwakEvent.objects.create(judul="Main Event")

        self.kirim(self.url_akun, event=lain.pk)

        self.assertEqual(EventRSVP.objects.filter(user=self.akun).count(), 2)

    def test_mentors_get_it_too_including_local_accounts(self):
        lokal = User.objects.create_user(username="mentor-ahmad")
        mentor = Profile.objects.create(
            user=lokal, nama_lengkap="Kak Ahmad", role=Profile.ROLE_MENTOR,
            auth_source=Profile.SOURCE_LOKAL,
        )

        self.kirim(reverse("siwak:panel_profil_rsvp", args=[mentor.pk]))

        self.assertEqual(EventRSVP.objects.get().user, lokal)

    # --- profil yang belum punya akun ------------------------------------------

    def test_a_profile_without_an_account_is_told_so_on_the_page(self):
        self.assertContains(self.client.get(self.url_tanpa), "Belum punya akun login")

    def test_a_profile_without_an_account_gets_a_pending_rsvp(self):
        response = self.kirim(self.url_tanpa, kehadiran="izin", alasan_izin="sakit")

        self.assertEqual(EventRSVP.objects.count(), 0)
        tertunda = RSVPTertunda.objects.get()
        self.assertEqual((tertunda.profile, tertunda.event), (self.tanpa_akun, self.event))
        self.assertEqual((tertunda.kehadiran, tertunda.alasan_izin), ("izin", "sakit"))
        self.assertRegex(tertunda.qr_registrasi_token, r"^[0-9a-f]{32}$")
        self.assertTrue(any("aktif otomatis" in m for m in _pesan(response)))
        self.assertContains(self.client.get(self.url_tanpa), "Menunggu login · Izin")

    def test_the_pending_rsvp_becomes_a_real_one_with_the_same_tokens_at_login(self):
        self.kirim(self.url_tanpa)
        tertunda = RSVPTertunda.objects.get()
        user = User.objects.create_user(username="fulan.dua")

        handle_cas_login(
            sender=self.__class__, user=user, username="fulan.dua",
            attributes={"npm": ["2606000002"], "nama": ["Fulan Dua"], "kd_org": ["01.00.12.01"]},
        )

        rsvp = EventRSVP.objects.get()
        self.assertEqual((rsvp.user, rsvp.qr_registrasi_token, rsvp.qr_kupon_token),
                         (user, tertunda.qr_registrasi_token, tertunda.qr_kupon_token))
        self.assertEqual(RSVPTertunda.objects.count(), 0)

    def test_submitting_again_before_login_corrects_the_answer_and_keeps_the_tokens(self):
        self.kirim(self.url_tanpa)
        awal = RSVPTertunda.objects.get()

        response = self.kirim(self.url_tanpa, kehadiran="izin", alasan_izin="sakit")

        lagi = RSVPTertunda.objects.get()
        self.assertEqual(lagi.pk, awal.pk)
        self.assertEqual((lagi.kehadiran, lagi.alasan_izin), ("izin", "sakit"))
        self.assertEqual(lagi.qr_registrasi_token, awal.qr_registrasi_token)
        self.assertEqual(lagi.qr_kupon_token, awal.qr_kupon_token)
        self.assertIn("RSVP Fulan Dua untuk Mentoring #1 diperbarui.", _pesan(response))

    def test_a_profile_with_neither_account_nor_npm_is_refused(self):
        mentor = Profile.objects.create(nama_lengkap="Kak Tanpa Npm", role=Profile.ROLE_MENTOR)
        url = reverse("siwak:panel_profil_rsvp", args=[mentor.pk])

        for response in (self.client.get(url), self.kirim(url)):
            self.assertEqual(response.status_code, 302)
            self.assertTrue(any("Isi NPM-nya dulu" in m for m in _pesan(response)))
        self.assertEqual(EventRSVP.objects.count() + RSVPTertunda.objects.count(), 0)

    def test_leftover_pending_rsvp_of_a_now_linked_profile_is_turned_into_a_real_one(self):
        self.kirim(self.url_tanpa)
        token = RSVPTertunda.objects.get().qr_registrasi_token
        self.tanpa_akun.user = User.objects.create_user(username="ditautkan")
        self.tanpa_akun.save()

        response = self.client.get(self.url_tanpa)

        self.assertContains(response, "Sudah RSVP · Hadir")
        self.assertEqual(EventRSVP.objects.get().qr_registrasi_token, token)
        self.assertEqual(RSVPTertunda.objects.count(), 0)

    def test_the_page_copes_with_no_events(self):
        SiwakEvent.objects.all().delete()
        response = self.client.get(self.url_akun)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Belum ada acara SIWAK")
