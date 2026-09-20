"""Inline editors in the panel lists: kelompok WhatsApp link and mentor NPM."""

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from .models import KelompokMentoring, Profile
from .sso import handle_cas_login

User = get_user_model()

LINK = "https://chat.whatsapp.com/AbCdEf123456"
LINK_BARU = "https://chat.whatsapp.com/ZyXwVu987654"


def _pesan(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class PanelLinkKelompokTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.punya = KelompokMentoring.objects.create(nama_kelompok="I-1", link_grup=LINK)
        self.kosong = KelompokMentoring.objects.create(nama_kelompok="I-2", link_grup="")
        self.url_daftar = reverse("siwak:panel_daftar", args=["kelompok"])
        self.url_kosong = reverse("siwak:panel_set_link", args=[self.kosong.pk])

    # --- the column itself -------------------------------------------------

    def test_the_list_has_a_link_column_that_posts_to_the_link_endpoint(self):
        response = self.client.get(self.url_daftar)

        kepala = [k["judul"] for k in response.context["kepala"]]
        self.assertIn("Link Grup WhatsApp", kepala)
        for item in response.context["baris"]:
            sel = next(s for s in item["sel"] if s["tipe"] == "isi_link")
            self.assertEqual(sel["url"], reverse("siwak:panel_set_link", args=[item["pk"]]))
            self.assertEqual(sel["nilai"], item["obj"].link_grup)

    def test_a_group_without_a_link_is_flagged_and_one_with_a_link_is_not(self):
        response = self.client.get(self.url_daftar)

        # Each row is drawn twice (table + phone card), so one empty group = 2 flags.
        self.assertContains(response, "Belum ada link", count=2)
        self.assertContains(response, f'value="{LINK}"', count=2)

    def test_the_column_is_sortable_and_puts_groups_without_a_link_first(self):
        naik = self.client.get(self.url_daftar, {"urut": "link"})
        turun = self.client.get(self.url_daftar, {"urut": "link", "arah": "turun"})

        self.assertEqual([b["obj"].pk for b in naik.context["baris"]], [self.kosong.pk, self.punya.pk])
        self.assertEqual([b["obj"].pk for b in turun.context["baris"]], [self.punya.pk, self.kosong.pk])

    # --- saving ------------------------------------------------------------

    def test_posting_a_link_saves_it(self):
        response = self.client.post(self.url_kosong, {"link_grup": LINK_BARU})

        self.kosong.refresh_from_db()
        self.assertEqual(self.kosong.link_grup, LINK_BARU)
        self.assertEqual(response.status_code, 302)
        self.assertIn("Link grup I-2 diperbarui.", _pesan(response))

    def test_surrounding_whitespace_is_dropped(self):
        self.client.post(self.url_kosong, {"link_grup": f"  {LINK_BARU}\n"})

        self.kosong.refresh_from_db()
        self.assertEqual(self.kosong.link_grup, LINK_BARU)

    def test_an_empty_post_clears_the_link(self):
        response = self.client.post(reverse("siwak:panel_set_link", args=[self.punya.pk]), {"link_grup": ""})

        self.punya.refresh_from_db()
        self.assertEqual(self.punya.link_grup, "")
        self.assertIn("Link grup I-1 dihapus.", _pesan(response))

    def test_an_invalid_link_is_rejected_and_the_old_one_stays(self):
        for buruk in ("bukan url", "javascript:alert(1)", "chat.whatsapp.com/tanpa-skema"):
            with self.subTest(buruk=buruk):
                response = self.client.post(
                    reverse("siwak:panel_set_link", args=[self.punya.pk]), {"link_grup": buruk}
                )

                self.punya.refresh_from_db()
                self.assertEqual(self.punya.link_grup, LINK)
                self.assertTrue(any("tidak disimpan" in m for m in _pesan(response)))

    def test_a_link_longer_than_the_column_is_rejected(self):
        panjang = "https://chat.whatsapp.com/" + "a" * 300

        response = self.client.post(self.url_kosong, {"link_grup": panjang})

        self.kosong.refresh_from_db()
        self.assertEqual(self.kosong.link_grup, "")
        self.assertTrue(any("tidak disimpan" in m for m in _pesan(response)))

    def test_only_the_posted_group_changes(self):
        self.client.post(self.url_kosong, {"link_grup": LINK_BARU})

        self.punya.refresh_from_db()
        self.assertEqual(self.punya.link_grup, LINK)

    def test_saving_returns_to_the_same_page_search_and_order(self):
        tujuan = f"{self.url_daftar}?q=I&urut=link&page=1"

        response = self.client.post(self.url_kosong, {"link_grup": LINK_BARU, "next": tujuan})

        self.assertEqual(response.url, tujuan)

    def test_saving_returns_to_the_group_list_by_default(self):
        response = self.client.post(self.url_kosong, {"link_grup": LINK_BARU})

        self.assertEqual(response.url, self.url_daftar)

    def test_an_offsite_next_is_ignored(self):
        response = self.client.post(
            self.url_kosong, {"link_grup": LINK_BARU, "next": "https://evil.example/"}
        )

        self.assertEqual(response.url, self.url_daftar)

    def test_an_unknown_group_is_a_404(self):
        response = self.client.post(reverse("siwak:panel_set_link", args=[99999]), {"link_grup": LINK})

        self.assertEqual(response.status_code, 404)

    # --- access ------------------------------------------------------------

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url_kosong).status_code, 405)

    def test_anonymous_visitors_are_sent_to_the_login(self):
        self.client.logout()

        response = self.client.post(self.url_kosong, {"link_grup": LINK_BARU})

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)
        self.kosong.refresh_from_db()
        self.assertEqual(self.kosong.link_grup, "")

    def test_non_staff_accounts_get_403(self):
        self.client.force_login(User.objects.create_user(username="biasa"))

        response = self.client.post(self.url_kosong, {"link_grup": LINK_BARU})

        self.assertEqual(response.status_code, 403)
        self.kosong.refresh_from_db()
        self.assertEqual(self.kosong.link_grup, "")


class PanelNpmMentorTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.k1 = KelompokMentoring.objects.create(nama_kelompok="I-1")
        # A mentor prepared by the CSV seed: name and group, no NPM, no account.
        self.siap = Profile.objects.create(
            nama_lengkap="Joko Pebrianto", role=Profile.ROLE_MENTOR, kelompok=self.k1
        )
        self.url = reverse("siwak:panel_set_npm", args=[self.siap.pk])
        self.url_daftar = reverse("siwak:panel_daftar", args=["mentor"])

    # --- the column itself -------------------------------------------------

    def test_the_mentor_list_npm_column_is_an_editor_posting_to_the_npm_endpoint(self):
        response = self.client.get(self.url_daftar)

        sel = next(s for s in response.context["baris"][0]["sel"] if s["tipe"] == "isi_npm")
        self.assertEqual(sel["url"], self.url)
        self.assertEqual(sel["nilai"], "")

    def test_a_mentor_without_npm_is_flagged(self):
        response = self.client.get(self.url_daftar)

        self.assertContains(response, "Belum ada NPM", count=2)  # table + phone card

    def test_a_mentor_with_npm_is_not_flagged_and_shows_the_value(self):
        self.siap.npm = "2106000001"
        self.siap.save()

        response = self.client.get(self.url_daftar)

        self.assertNotContains(response, "Belum ada NPM")
        self.assertContains(response, 'value="2106000001"', count=2)

    def test_the_mentee_list_keeps_a_plain_npm_column(self):
        Profile.objects.create(
            npm="2506000001", nama_lengkap="Mentee", jurusan="IK", role=Profile.ROLE_MENTEE
        )

        response = self.client.get(reverse("siwak:panel_daftar", args=["peserta"]))

        tipe = {s["tipe"] for b in response.context["baris"] for s in b["sel"]}
        self.assertNotIn("isi_npm", tipe)

    # --- saving ------------------------------------------------------------

    def test_posting_an_npm_saves_it(self):
        response = self.client.post(self.url, {"npm": " 2106000001 "})

        self.siap.refresh_from_db()
        self.assertEqual(self.siap.npm, "2106000001")
        self.assertEqual(self.siap.role, Profile.ROLE_MENTOR)
        self.assertEqual(self.siap.kelompok, self.k1)
        self.assertIn("NPM Joko Pebrianto diperbarui.", _pesan(response))

    def test_a_prepared_mentor_is_claimed_at_sso_login_once_the_npm_is_saved(self):
        """The reason the column is editable: NPM is how the row meets the SSO account."""
        self.client.post(self.url, {"npm": "2106000001"})
        akun = User.objects.create_user(username="joko.pebrianto")

        handle_cas_login(
            sender=self.__class__,
            user=akun,
            username="joko.pebrianto",
            attributes={"npm": ["2106000001"], "nama": ["Joko Pebrianto"], "kd_org": ["01.00.12.01"]},
        )

        self.siap.refresh_from_db()
        self.assertEqual(self.siap.user, akun)
        self.assertEqual(self.siap.role, Profile.ROLE_MENTOR)
        self.assertEqual(self.siap.kelompok, self.k1)
        self.assertEqual(Profile.objects.count(), 1)

    def test_an_npm_can_be_corrected(self):
        self.siap.npm = "2106000001"
        self.siap.save()

        self.client.post(self.url, {"npm": "2106000009"})

        self.siap.refresh_from_db()
        self.assertEqual(self.siap.npm, "2106000009")

    def test_saving_the_same_npm_again_is_a_quiet_no_op(self):
        self.siap.npm = "2106000001"
        self.siap.save()

        response = self.client.post(self.url, {"npm": "2106000001"})

        self.assertEqual(_pesan(response), [])

    def test_an_empty_npm_is_rejected(self):
        self.siap.npm = "2106000001"
        self.siap.save()

        response = self.client.post(self.url, {"npm": "  "})

        self.siap.refresh_from_db()
        self.assertEqual(self.siap.npm, "2106000001")
        self.assertTrue(any("tidak boleh kosong" in m for m in _pesan(response)))

    def test_a_non_numeric_or_overlong_npm_is_rejected(self):
        for buruk in ("21O6000001", "2106 000001", "abc", "1" * 21):
            with self.subTest(buruk=buruk):
                response = self.client.post(self.url, {"npm": buruk})

                self.siap.refresh_from_db()
                self.assertIsNone(self.siap.npm)
                self.assertTrue(any("tidak disimpan" in m for m in _pesan(response)))

    def test_an_npm_already_used_by_another_profile_is_rejected(self):
        Profile.objects.create(
            npm="2106000001", nama_lengkap="Sudah Punya", jurusan="IK", role=Profile.ROLE_MENTEE
        )

        response = self.client.post(self.url, {"npm": "2106000001"})

        self.siap.refresh_from_db()
        self.assertIsNone(self.siap.npm)
        self.assertTrue(any("sudah dipakai Sudah Punya" in m for m in _pesan(response)))

    def test_a_non_sso_mentor_can_never_be_given_an_npm(self):
        """Local accounts must keep npm NULL: it is what keeps them apart from CAS accounts."""
        lokal = Profile.objects.create(
            nama_lengkap="Mentor Lokal", role=Profile.ROLE_MENTOR,
            auth_source=Profile.SOURCE_LOKAL, user=User.objects.create_user(username="mentor-lokal"),
        )

        response = self.client.post(reverse("siwak:panel_set_npm", args=[lokal.pk]), {"npm": "2106000002"})

        self.assertEqual(response.status_code, 404)
        lokal.refresh_from_db()
        self.assertIsNone(lokal.npm)

    def test_a_mentee_is_not_editable_through_this_endpoint(self):
        mentee = Profile.objects.create(
            npm="2506000001", nama_lengkap="Mentee", jurusan="IK", role=Profile.ROLE_MENTEE
        )

        response = self.client.post(reverse("siwak:panel_set_npm", args=[mentee.pk]), {"npm": "2506000002"})

        self.assertEqual(response.status_code, 404)
        mentee.refresh_from_db()
        self.assertEqual(mentee.npm, "2506000001")

    def test_only_the_posted_mentor_changes(self):
        lain = Profile.objects.create(nama_lengkap="Mentor Lain", role=Profile.ROLE_MENTOR)

        self.client.post(self.url, {"npm": "2106000001"})

        lain.refresh_from_db()
        self.assertIsNone(lain.npm)

    def test_saving_returns_to_the_same_page_and_search(self):
        tujuan = f"{self.url_daftar}?q=Joko&page=1"

        response = self.client.post(self.url, {"npm": "2106000001", "next": tujuan})

        self.assertEqual(response.url, tujuan)

    def test_saving_returns_to_the_mentor_list_by_default(self):
        response = self.client.post(self.url, {"npm": "2106000001"})

        self.assertEqual(response.url, self.url_daftar)

    # --- access ------------------------------------------------------------

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_non_staff_accounts_get_403(self):
        self.client.force_login(User.objects.create_user(username="biasa"))

        response = self.client.post(self.url, {"npm": "2106000001"})

        self.assertEqual(response.status_code, 403)
        self.siap.refresh_from_db()
        self.assertIsNone(self.siap.npm)

    def test_anonymous_visitors_are_sent_to_the_login(self):
        self.client.logout()

        response = self.client.post(self.url, {"npm": "2106000001"})

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)
