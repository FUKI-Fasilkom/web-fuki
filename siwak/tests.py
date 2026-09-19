"""Tests for SIWAK's CAS authentication and student-profile synchronization."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    EventRSVP,
    KelompokMentoring,
    MabaProfile,
    Mentor,
    PesertaMentoring,
    SiwakEvent,
)
from .sso import get_attribute, handle_cas_login, sync_maba_profile


User = get_user_model()


class GetAttributeTests(TestCase):
    """Verify normalization of attribute values returned by CAS."""

    def test_returns_trimmed_scalar_value(self):
        """A scalar CAS attribute should be returned without surrounding spaces."""
        attributes = {"npm": " 2506534245 "}

        self.assertEqual(get_attribute(attributes, "npm"), "2506534245")

    def test_returns_first_value_from_list(self):
        """django-cas-ng may provide an attribute as a list; use its first item."""
        attributes = {"nama": [" Fiqhi Deski Ismail ", "Nama Lain"]}

        self.assertEqual(get_attribute(attributes, "nama"), "Fiqhi Deski Ismail")

    def test_returns_empty_string_for_missing_or_empty_value(self):
        """Missing attributes and empty CAS lists should be treated as empty values."""
        self.assertEqual(get_attribute({}, "npm"), "")
        self.assertEqual(get_attribute({"npm": []}, "npm"), "")


class SyncMabaProfileTests(TestCase):
    """Verify synchronization between Django users, profiles, and mentoring data."""

    def setUp(self):
        self.user = User.objects.create_user(username="2506534245")

    def test_claims_profile_registered_by_admin_before_first_login(self):
        """A profile pre-registered by an admin should be claimed, not duplicated."""
        didaftarkan_admin = MabaProfile.objects.create(
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
        )
        maba_lain = MabaProfile.objects.create(
            npm="2400000000",
            nama_lengkap="Mahasiswa Lain",
            jurusan="SI",
        )

        profile = sync_maba_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        maba_lain.refresh_from_db()
        self.assertEqual(profile.pk, didaftarkan_admin.pk)
        self.assertEqual(MabaProfile.objects.count(), 2)
        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.npm, "2506534245")
        self.assertEqual(profile.angkatan, "2025")
        self.assertIsNone(maba_lain.user)

    def test_creates_participant_row_without_kelompok(self):
        """Logging in should make the student a participant awaiting a group."""
        profile = sync_maba_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        peserta = PesertaMentoring.objects.get(maba=profile)
        self.assertIsNone(peserta.kelompok)

    def test_keeps_existing_group_assignment_on_later_login(self):
        """A student already placed in a group must stay in it after logging in again."""
        profile = MabaProfile.objects.create(
            npm="2506534245", nama_lengkap="Fiqhi Deski Ismail", jurusan="IK",
        )
        kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")
        PesertaMentoring.objects.create(maba=profile, kelompok=kelompok)

        sync_maba_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        self.assertEqual(PesertaMentoring.objects.count(), 1)
        self.assertEqual(PesertaMentoring.objects.get().kelompok, kelompok)

    def test_updates_existing_profile_without_creating_duplicate(self):
        """Later logins should refresh the same profile instead of duplicating it."""
        profile = MabaProfile.objects.create(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Nama Lama",
            jurusan="SI",
            angkatan="2024",
        )

        updated_profile = sync_maba_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        self.assertEqual(updated_profile.pk, profile.pk)
        self.assertEqual(MabaProfile.objects.count(), 1)
        self.assertEqual(updated_profile.nama_lengkap, "Fiqhi Deski Ismail")
        self.assertEqual(updated_profile.jurusan, "IK")
        self.assertEqual(updated_profile.angkatan, "2025")

    def test_does_not_touch_participants_belonging_to_another_student(self):
        """Synchronization must leave another student's group placement alone."""
        other_user = User.objects.create_user(username="2400000000")
        other_profile = MabaProfile.objects.create(
            user=other_user,
            npm="2400000000",
            nama_lengkap="Mahasiswa Lain",
            jurusan="SI",
        )
        kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")
        other_participant = PesertaMentoring.objects.create(maba=other_profile, kelompok=kelompok)

        sync_maba_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        other_participant.refresh_from_db()
        self.assertEqual(other_participant.maba, other_profile)
        self.assertEqual(other_participant.kelompok, kelompok)


class HandleCasLoginTests(TestCase):
    """Verify conversion of validated CAS attributes into local student data."""

    def setUp(self):
        self.user = User.objects.create_user(username="cas-user")

    def test_creates_maba_profile_from_cas_attributes(self):
        """A complete CAS response should produce the expected MabaProfile."""
        handle_cas_login(
            sender=self.__class__,
            user=self.user,
            username="cas-user",
            attributes={
                "npm": ["2506534245"],
                "nama": ["Fiqhi Deski Ismail"],
                "kd_org": ["01.00.12.01"],
            },
        )

        profile = MabaProfile.objects.get(user=self.user)
        self.assertEqual(profile.npm, "2506534245")
        self.assertEqual(profile.nama_lengkap, "Fiqhi Deski Ismail")
        self.assertEqual(profile.jurusan, "IK")
        self.assertEqual(profile.angkatan, "2025")

    def test_rejects_missing_required_attributes(self):
        """Login should fail when CAS omits identity data required by SIWAK."""
        cases = (
            ({"nama": "Fiqhi", "kd_org": "01.00.12.01"}, "NPM"),
            ({"npm": "2506534245", "kd_org": "01.00.12.01"}, "nama lengkap"),
            ({"npm": "2506534245", "nama": "Fiqhi"}, "kode jurusan"),
        )

        for attributes, missing_field in cases:
            with self.subTest(missing_field=missing_field):
                with self.assertRaisesRegex(ValueError, missing_field):
                    handle_cas_login(
                        sender=self.__class__,
                        user=self.user,
                        username="cas-user",
                        attributes=attributes,
                    )

        self.assertFalse(MabaProfile.objects.filter(user=self.user).exists())

    def test_rejects_unknown_program_code(self):
        """An unmapped kd_org program code must not create an invalid profile."""
        with self.assertRaisesRegex(ValueError, "Kode program tidak dikenal"):
            handle_cas_login(
                sender=self.__class__,
                user=self.user,
                username="cas-user",
                attributes={
                    "npm": "2506534245",
                    "nama": "Fiqhi Deski Ismail",
                    "kd_org": "99.00.12.01",
                },
            )


class AuthenticationProtectionTests(TestCase):
    """Verify that protected SIWAK pages require an authenticated session."""

    def test_anonymous_user_is_redirected_to_cas_login(self):
        """Anonymous access should preserve the destination through the next query."""
        protected_url = reverse("siwak:tugas_list")

        response = self.client.get(protected_url)

        expected_login_url = reverse("siwak:cas_ng_login")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{expected_login_url}?next={protected_url}")

class PanelAccessTests(TestCase):
    """Verify who may open the SIWAK management panel at /siwak/admin/."""

    def test_anonymous_user_is_sent_to_the_admin_login(self):
        """Anonymous access should land on the admin login, keeping the destination."""
        panel_url = reverse("siwak:panel_beranda")

        response = self.client.get(panel_url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('admin:login')}?next={panel_url}")

    def test_signed_in_student_gets_forbidden_instead_of_a_login_loop(self):
        """A logged-in non-staff user must get 403, not another login redirect."""
        self.client.force_login(User.objects.create_user(username="maba"))

        response = self.client.get(reverse("siwak:panel_beranda"))

        self.assertEqual(response.status_code, 403)

    def test_staff_user_can_open_every_panel_page(self):
        """Each registered panel page should render for a staff account."""
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))

        for url in (
            reverse("siwak:panel_beranda"),
            reverse("siwak:panel_bagian", args=["kelompok"]),
            reverse("siwak:panel_info"),
            reverse("siwak:panel_daftar", args=["kelompok"]),
            reverse("siwak:panel_daftar", args=["mentor"]),
            reverse("siwak:panel_daftar", args=["peserta"]),
            reverse("siwak:panel_tambah", args=["peserta"]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_unknown_data_type_returns_not_found(self):
        """A made-up resource slug must not fall through to a server error."""
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))

        response = self.client.get(reverse("siwak:panel_daftar", args=["ngawur"]))

        self.assertEqual(response.status_code, 404)


class PanelPesertaTests(TestCase):
    """Verify the participant form writes identity and placement in one step."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")

    def test_adding_a_participant_creates_profile_and_placement(self):
        """One submitted form should produce both the profile and its group row."""
        response = self.client.post(reverse("siwak:panel_tambah", args=["peserta"]), {
            "nama_lengkap": "Marwa Muhlashon",
            "npm": "2506000009",
            "jurusan": "SI",
            "angkatan": "2025",
            "kelompok": self.kelompok.pk,
        })

        self.assertEqual(response.status_code, 302)
        profil = MabaProfile.objects.get(npm="2506000009")
        self.assertEqual(profil.nama_lengkap, "Marwa Muhlashon")
        self.assertEqual(PesertaMentoring.objects.get(maba=profil).kelompok, self.kelompok)

    def test_participant_without_group_is_still_recorded(self):
        """Leaving the group empty should still register the student as a participant."""
        self.client.post(reverse("siwak:panel_tambah", args=["peserta"]), {
            "nama_lengkap": "Belum Ditempatkan",
            "npm": "2506000010",
            "jurusan": "IK",
            "angkatan": "",
            "kelompok": "",
        })

        peserta = PesertaMentoring.objects.get(maba__npm="2506000010")
        self.assertIsNone(peserta.kelompok)

    def test_deleting_a_participant_removes_the_placement_too(self):
        """Removing the profile must not leave an orphaned placement behind."""
        profil = MabaProfile.objects.create(npm="2506000011", nama_lengkap="Hapus Aku", jurusan="KA")
        PesertaMentoring.objects.create(maba=profil, kelompok=self.kelompok)

        self.client.post(reverse("siwak:panel_hapus", args=["peserta", profil.pk]))

        self.assertFalse(MabaProfile.objects.filter(pk=profil.pk).exists())
        self.assertFalse(PesertaMentoring.objects.exists())


class PanelRelasiTests(TestCase):
    """Verify the list-page dropdowns rewrite mentor and group relations."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.k1 = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")
        self.k2 = KelompokMentoring.objects.create(nama_kelompok="Kelompok 2")
        self.maba = MabaProfile.objects.create(
            npm="2506000020", nama_lengkap="Pindah Aku", jurusan="IK"
        )
        self.peserta = PesertaMentoring.objects.create(maba=self.maba, kelompok=self.k1)
        self.url_kelompok = reverse("siwak:panel_set_kelompok", args=[self.maba.pk])
        self.url_mentor = reverse("siwak:panel_set_mentor")

    def test_the_dropdown_moves_a_mentee_to_another_group(self):
        """Picking another group in the participant list should relocate them."""
        self.client.post(self.url_kelompok, {"kelompok": str(self.k2.pk)})

        self.peserta.refresh_from_db()
        self.assertEqual(self.peserta.kelompok, self.k2)

    def test_the_empty_choice_takes_the_mentee_out_of_every_group(self):
        """The blank option should leave the student unplaced, not unchanged."""
        self.client.post(self.url_kelompok, {"kelompok": ""})

        self.peserta.refresh_from_db()
        self.assertIsNone(self.peserta.kelompok)

    def test_a_student_without_a_participant_row_can_still_be_placed(self):
        """Staff-registered students have no placement row until they get one."""
        baru = MabaProfile.objects.create(
            npm="2506000022", nama_lengkap="Baru Didaftarkan", jurusan="SI"
        )

        self.client.post(
            reverse("siwak:panel_set_kelompok", args=[baru.pk]),
            {"kelompok": str(self.k1.pk)},
        )

        self.assertEqual(PesertaMentoring.objects.get(maba=baru).kelompok, self.k1)

    def test_moving_one_mentee_leaves_the_other_rows_alone(self):
        """Editing a single row must never touch the rest of the list."""
        lain = PesertaMentoring.objects.create(
            maba=MabaProfile.objects.create(
                npm="2506000021", nama_lengkap="Peserta Lain", jurusan="SI"
            ),
            kelompok=self.k1,
        )

        self.client.post(self.url_kelompok, {"kelompok": str(self.k2.pk)})

        lain.refresh_from_db()
        self.assertEqual(lain.kelompok, self.k1)

    def test_the_group_list_can_assign_and_release_a_mentor(self):
        """The mentor chips and their dropdown write the relation both ways."""
        mentor = Mentor.objects.create(nama="Kak Ahmad")

        self.client.post(self.url_mentor, {
            "aksi": "tambah", "kelompok": str(self.k1.pk), "mentor": str(mentor.pk),
        })
        self.assertEqual(list(self.k1.mentor_list.all()), [mentor])

        self.client.post(self.url_mentor, {
            "aksi": "hapus", "kelompok": str(self.k1.pk), "mentor": str(mentor.pk),
        })
        self.assertEqual(self.k1.mentor_list.count(), 0)

    def test_the_mentor_list_sets_the_group_from_its_own_side(self):
        """The mentor page has one dropdown, and it writes the same relation."""
        mentor = Mentor.objects.create(nama="Kak Fatimah")

        self.client.post(
            reverse("siwak:panel_set_mentor_kelompok", args=[mentor.pk]),
            {"kelompok": str(self.k2.pk)},
        )

        mentor.refresh_from_db()
        self.assertEqual(mentor.kelompok, self.k2)

    def test_the_mentor_dropdown_can_release_the_group(self):
        """The blank option means "holds nothing", not "leave it as it was"."""
        mentor = Mentor.objects.create(nama="Kak Fatimah", kelompok=self.k2)

        self.client.post(
            reverse("siwak:panel_set_mentor_kelompok", args=[mentor.pk]),
            {"kelompok": ""},
        )

        mentor.refresh_from_db()
        self.assertIsNone(mentor.kelompok)

    def test_a_mentor_never_holds_two_groups_at_once(self):
        """Assigning a mentor who already has a group moves them, and the group
        they left really loses them."""
        mentor = Mentor.objects.create(nama="Kak Fatimah", kelompok=self.k1)

        self.client.post(self.url_mentor, {
            "aksi": "tambah", "kelompok": str(self.k2.pk), "mentor": str(mentor.pk),
        })

        mentor.refresh_from_db()
        self.assertEqual(mentor.kelompok, self.k2)
        self.assertEqual(self.k1.mentor_list.count(), 0)

    def test_a_group_keeps_every_mentor_that_was_added_to_it(self):
        """The rule runs one way only: a group may still hold several mentors."""
        satu = Mentor.objects.create(nama="Kak Ahmad")
        dua = Mentor.objects.create(nama="Kak Fatimah")

        for mentor in (satu, dua):
            self.client.post(self.url_mentor, {
                "aksi": "tambah", "kelompok": str(self.k1.pk), "mentor": str(mentor.pk),
            })

        self.assertEqual(self.k1.mentor_list.count(), 2)

    def test_editing_a_relation_over_get_is_refused(self):
        """These routes change data, so a plain link must not be able to fire them."""
        self.assertEqual(self.client.get(self.url_kelompok).status_code, 405)
        self.assertEqual(self.client.get(self.url_mentor).status_code, 405)

    def test_saving_returns_to_the_exact_list_page_it_came_from(self):
        """Search and sort order must survive an inline edit."""
        asal = f"{reverse('siwak:panel_daftar', args=['peserta'])}?q=Pindah&urut=kelompok"

        response = self.client.post(
            self.url_kelompok, {"kelompok": str(self.k2.pk), "next": asal}
        )

        self.assertEqual(response.url, asal)

    def test_a_return_address_outside_the_site_is_ignored(self):
        """`next` comes from the page, so it still has to be checked."""
        response = self.client.post(
            self.url_kelompok,
            {"kelompok": str(self.k2.pk), "next": "https://contoh.invalid/curi"},
        )

        self.assertEqual(response.url, reverse("siwak:panel_daftar", args=["peserta"]))


class PanelUrutanTests(TestCase):
    """Verify the clickable column headers reorder participants and mentors."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.k2 = KelompokMentoring.objects.create(nama_kelompok="Kelompok 2")
        self.k10 = KelompokMentoring.objects.create(nama_kelompok="Kelompok 10")

    def _nama_peserta(self, **kueri):
        response = self.client.get(reverse("siwak:panel_daftar", args=["peserta"]), kueri)
        return [baris["obj"].nama_lengkap for baris in response.context["baris"]]

    def _buat_peserta(self, nama, npm, kelompok):
        PesertaMentoring.objects.create(
            maba=MabaProfile.objects.create(npm=npm, nama_lengkap=nama, jurusan="IK"),
            kelompok=kelompok,
        )

    def test_participants_are_listed_by_name_by_default(self):
        """Without a sort choice the list should still be predictable."""
        self._buat_peserta("Zulfa", "2506000031", self.k2)
        self._buat_peserta("Aisyah", "2506000032", self.k10)

        self.assertEqual(self._nama_peserta(), ["Aisyah", "Zulfa"])

    def test_sorting_by_group_counts_group_numbers_not_letters(self):
        """"Kelompok 2" must come before "Kelompok 10", not after it."""
        self._buat_peserta("Aisyah", "2506000032", self.k10)
        self._buat_peserta("Zulfa", "2506000031", self.k2)

        self.assertEqual(self._nama_peserta(urut="kelompok"), ["Zulfa", "Aisyah"])

    def test_participants_without_a_group_are_listed_last(self):
        """Unplaced students are the ones staff need to see, but not on top of
        the group ordering they just asked for."""
        self._buat_peserta("Aisyah", "2506000032", self.k2)
        self._buat_peserta("Belum Punya", "2506000033", None)

        self.assertEqual(
            self._nama_peserta(urut="kelompok"), ["Aisyah", "Belum Punya"]
        )
        self.assertEqual(
            self._nama_peserta(urut="kelompok", arah="turun"), ["Aisyah", "Belum Punya"]
        )

    def test_the_name_column_can_be_reversed(self):
        """Clicking an already-sorted column flips it instead of doing nothing."""
        self._buat_peserta("Aisyah", "2506000032", self.k2)
        self._buat_peserta("Zulfa", "2506000031", self.k2)

        self.assertEqual(self._nama_peserta(urut="nama", arah="turun"), ["Zulfa", "Aisyah"])

    def test_an_unknown_sort_key_falls_back_instead_of_failing(self):
        """A hand-edited address must not be able to break the page."""
        self._buat_peserta("Aisyah", "2506000032", self.k2)

        response = self.client.get(
            reverse("siwak:panel_daftar", args=["peserta"]), {"urut": "ngawur"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["kunci_urut"], "nama")

    def test_mentors_can_be_sorted_by_the_group_they_hold(self):
        """The mentor list gets the same group ordering as the participants."""
        pemegang_k10 = Mentor.objects.create(nama="Kak Ahmad")
        pemegang_k2 = Mentor.objects.create(nama="Kak Zaid")
        self.k10.mentor_list.add(pemegang_k10)
        self.k2.mentor_list.add(pemegang_k2)

        response = self.client.get(
            reverse("siwak:panel_daftar", args=["mentor"]), {"urut": "kelompok"}
        )

        self.assertEqual(
            [baris["obj"].nama for baris in response.context["baris"]],
            ["Kak Zaid", "Kak Ahmad"],
        )

    def test_groups_can_be_sorted_by_how_full_they_are(self):
        """The participant count is an aggregate, so its ordering needs an
        annotation — a plain Count() in order_by() raises FieldError."""
        self._buat_peserta("Aisyah", "2506000032", self.k10)

        response = self.client.get(
            reverse("siwak:panel_daftar", args=["kelompok"]), {"urut": "peserta"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [baris["obj"].nama_kelompok for baris in response.context["baris"]],
            ["Kelompok 2", "Kelompok 10"],
        )

    def test_sorting_keeps_the_search_term(self):
        """Sorting a filtered list must not quietly drop the filter."""
        self._buat_peserta("Aisyah", "2506000032", self.k2)
        self._buat_peserta("Zulfa", "2506000031", self.k2)

        self.assertEqual(self._nama_peserta(q="Zulfa", urut="kelompok"), ["Zulfa"])


class PanelEventTests(TestCase):
    """Verify event management, including the RSVP open/close switch."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.event = SiwakEvent.objects.create(judul="Main Event", rsvp_dibuka=False)

    def test_toggle_opens_and_closes_rsvp(self):
        """Each POST to the switch should flip the RSVP state exactly once."""
        self.client.post(reverse("siwak:panel_rsvp_toggle", args=[self.event.pk]))
        self.event.refresh_from_db()
        self.assertTrue(self.event.rsvp_dibuka)

        self.client.post(reverse("siwak:panel_rsvp_toggle", args=[self.event.pk]))
        self.event.refresh_from_db()
        self.assertFalse(self.event.rsvp_dibuka)

    def test_toggle_rejects_a_get_request(self):
        """A state change must not be reachable by simply opening a URL."""
        response = self.client.get(reverse("siwak:panel_rsvp_toggle", args=[self.event.pk]))

        self.assertEqual(response.status_code, 405)
        self.event.refresh_from_db()
        self.assertFalse(self.event.rsvp_dibuka)

    def test_rsvp_export_returns_a_csv_attachment(self):
        """The export button should hand back a downloadable CSV, not a web page."""
        response = self.client.get(reverse("siwak:panel_rsvp_csv", args=[self.event.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("attachment;", response["Content-Disposition"])


class PanelRsvpStatusTests(TestCase):
    """Verify the QR status dropdowns on the RSVP list."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.event = SiwakEvent.objects.create(judul="Main Event", rsvp_dibuka=True)
        self.rsvp = EventRSVP.objects.create(
            event=self.event, user=User.objects.create_user(username="maba1")
        )
        self.url = reverse("siwak:panel_rsvp_status", args=[self.rsvp.pk])

    def test_marking_attendance_also_stamps_the_check_in_time(self):
        """A hand-set status must leave the same trace a QR scan would."""
        self.client.post(self.url, {"medan": "kehadiran", "nilai": "hadir"})

        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status_kehadiran, "hadir")
        self.assertIsNotNone(self.rsvp.checked_in_at)

    def test_undoing_attendance_clears_the_check_in_time(self):
        """Otherwise a row reads "belum hadir" while still holding a check-in time."""
        self.rsvp.status_kehadiran = "hadir"
        self.rsvp.checked_in_at = timezone.now()
        self.rsvp.save()

        self.client.post(self.url, {"medan": "kehadiran", "nilai": "belum_hadir"})

        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status_kehadiran, "belum_hadir")
        self.assertIsNone(self.rsvp.checked_in_at)

    def test_redeeming_the_coupon_stamps_its_own_time(self):
        """The coupon column keeps its own status and timestamp."""
        self.client.post(self.url, {"medan": "kupon", "nilai": "redeemed"})

        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status_kupon, "redeemed")
        self.assertIsNotNone(self.rsvp.redeemed_at)
        self.assertIsNone(self.rsvp.checked_in_at)

    def test_an_unknown_status_is_refused(self):
        """A hand-edited form must not be able to write a value the model
        does not offer."""
        self.client.post(self.url, {"medan": "kehadiran", "nilai": "mungkin"})

        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status_kehadiran, "belum_hadir")

    def test_an_unknown_column_is_refused(self):
        """`medan` decides which field gets written, so it is checked too."""
        response = self.client.post(self.url, {"medan": "gaji", "nilai": "hadir"})

        self.assertEqual(response.status_code, 302)
        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status_kehadiran, "belum_hadir")

    def test_changing_a_status_over_get_is_refused(self):
        """These routes change data, so a plain link must not fire them."""
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_the_export_uses_the_new_column_names(self):
        """The CSV header should match what the page now calls these columns."""
        response = self.client.get(reverse("siwak:panel_rsvp_csv", args=[self.event.pk]))

        kepala = response.content.decode("utf-8").splitlines()[0]
        self.assertIn("QR Kehadiran", kepala)
        self.assertIn("QR Kupon", kepala)
