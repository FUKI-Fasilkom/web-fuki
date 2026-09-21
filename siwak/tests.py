"""Tests for SIWAK's CAS/SSO authentication (PRD 7) that drives Profile
sync, plus the QR & RSVP features (PRD 5.2 / 6 / 8) and the
access control around qr_verify (admin-only after the admin_scan removal).

Security/functional notes asserted here (regression guards):
  * qr_verify GET is read-only (shows a confirm page); the actual check-in /
    kupon redemption only happens on a CSRF-protected POST, so a passive
    `<img src=".../qr/...">` load can't flip attendance state.
  * The mutation runs inside a transaction with `SELECT ... FOR UPDATE`, so
    two concurrent scans can't both succeed (TOCTOU closed).
  * No-show / izin RSVPs can no longer be checked in — the scan rejects them.
  * qr_verify signatures are still accepted for 30 days (long-lived bearer
    token) unless someone changes that policy.
  * The RSVP page renders `npm` as a `disabled` HTML input, but disabled
    fields fall back to their `initial` (the SSO profile NPM), so a browser
    submit still creates the RSVP — no data loss on that page.
"""

import base64
import time
import datetime
import zipfile
from io import BytesIO
from unittest.mock import patch
from urllib.parse import unquote

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.contrib import admin
from django.db import transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from .forms import CariKelompokForm
from .models import (
    Answer,
    AssessmentAspect,
    Choice,
    EventRSVP,
    JURUSAN_CHOICES,
    KelompokMentoring,
    Profile,
    MenteeAssessment,
    MentoringSession,
    Question,
    SiwakEvent,
    SiwakInfo,
    Tugas,
    TugasSubmission
)
from django.utils import formats, timezone

from .services.qrcode_service import (
    SIGNING_SALT,
    kupon_qr_data_uri,
    registrasi_qr_data_uri,
    sign_payload,
    unsign_payload
)
from .sso import (
    KD_ORG_PROGRAM_MAP,
    get_attribute,
    handle_cas_login,
    sync_profile,
)


User = get_user_model()


class TestStorageIsolation(TestCase):
    """The test command must not send fixtures to the configured S3 bucket."""

    def test_default_media_storage_is_in_memory(self):
        self.assertEqual(
            settings.STORAGES["default"]["BACKEND"],
            "django.core.files.storage.InMemoryStorage",
        )
        self.assertEqual(default_storage.__class__.__name__, "InMemoryStorage")


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


class JurusanChoiceTests(TestCase):
    """Pilihan jurusan aktif harus konsisten di model, form, dan mapping SSO."""

    def test_si_iup_is_not_available_in_model(self):
        self.assertNotIn("SI-IUP", dict(JURUSAN_CHOICES))

    def test_sso_mapping_only_uses_supported_departments(self):
        supported_departments = {value for value, _label in JURUSAN_CHOICES}

        self.assertNotIn("SI-IUP", KD_ORG_PROGRAM_MAP.values())
        self.assertLessEqual(set(KD_ORG_PROGRAM_MAP.values()), supported_departments)


class JurusanChoiceTests(TestCase):
    """Pilihan jurusan aktif harus konsisten di model, form, dan mapping SSO."""

    def test_si_iup_is_not_available_in_model(self):
        self.assertNotIn("SI-IUP", dict(JURUSAN_CHOICES))

    def test_sso_mapping_only_uses_supported_departments(self):
        supported_departments = {value for value, _label in JURUSAN_CHOICES}

        self.assertNotIn("SI-IUP", KD_ORG_PROGRAM_MAP.values())
        self.assertLessEqual(set(KD_ORG_PROGRAM_MAP.values()), supported_departments)


class SyncProfileTests(TestCase):
    """Verify synchronization between Django users and their Profile."""

    def setUp(self):
        self.user = User.objects.create_user(username="2506534245")

    def test_claims_profile_registered_by_admin_before_first_login(self):
        """A profile pre-registered by an admin should be claimed, not duplicated."""
        didaftarkan_admin = Profile.objects.create(
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
        )
        mahasiswa_lain = Profile.objects.create(
            npm="2400000000",
            nama_lengkap="Mahasiswa Lain",
            jurusan="SI",
        )

        profile = sync_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        mahasiswa_lain.refresh_from_db()
        self.assertEqual(profile.pk, didaftarkan_admin.pk)
        self.assertEqual(Profile.objects.count(), 2)
        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.npm, "2506534245")
        self.assertEqual(profile.angkatan, "2025")
        self.assertIsNone(mahasiswa_lain.user)

    def test_new_login_creates_a_profile_without_role_or_kelompok(self):
        """A brand-new login is neither mentee nor mentor; staff decide later."""
        profile = sync_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        self.assertIsNone(profile.role)
        self.assertIsNone(profile.kelompok)

    def test_keeps_existing_group_assignment_on_later_login(self):
        """A student already placed in a group must stay in it after logging in again."""
        kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")
        Profile.objects.create(
            npm="2506534245", nama_lengkap="Fiqhi Deski Ismail", jurusan="IK",
            kelompok=kelompok,
        )

        profile = sync_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        self.assertEqual(Profile.objects.count(), 1)
        self.assertEqual(profile.kelompok, kelompok)

    def test_updates_existing_profile_without_creating_duplicate(self):
        """Later logins should refresh the same profile instead of duplicating it."""
        profile = Profile.objects.create(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Nama Lama",
            jurusan="SI",
            angkatan="2024",
        )

        updated_profile = sync_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        self.assertEqual(updated_profile.pk, profile.pk)
        self.assertEqual(Profile.objects.count(), 1)
        self.assertEqual(updated_profile.nama_lengkap, "Fiqhi Deski Ismail")
        self.assertEqual(updated_profile.jurusan, "IK")
        self.assertEqual(updated_profile.angkatan, "2025")

    def test_does_not_touch_another_students_group_placement(self):
        """Synchronization must leave another student's group placement alone."""
        other_user = User.objects.create_user(username="2400000000")
        kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")
        other_profile = Profile.objects.create(
            user=other_user,
            npm="2400000000",
            nama_lengkap="Mahasiswa Lain",
            jurusan="SI",
            kelompok=kelompok,
        )

        sync_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        other_profile.refresh_from_db()
        self.assertEqual(other_profile.user, other_user)
        self.assertEqual(other_profile.kelompok, kelompok)

    def test_sync_never_changes_role_or_group_of_the_account_owner(self):
        """SSO supplies identity only. Role and group belong to the staff, so a
        mentor stays a mentor (and keeps their group) across every login."""
        kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")
        Profile.objects.create(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Kak Fiqhi",
            jurusan="IK",
            role=Profile.ROLE_MENTOR,
            kelompok=kelompok,
        )

        profile = sync_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        self.assertEqual(profile.role, Profile.ROLE_MENTOR)
        self.assertEqual(profile.kelompok, kelompok)
        self.assertEqual(profile.nama_lengkap, "Fiqhi Deski Ismail")


class HandleCasLoginTests(TestCase):
    """Verify conversion of validated CAS attributes into local student data."""

    def setUp(self):
        self.user = User.objects.create_user(username="cas-user")

    def test_creates_profil_from_cas_attributes(self):
        """A complete CAS response should produce the expected Profile."""
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

        profile = Profile.objects.get(user=self.user)
        self.assertEqual(profile.npm, "2506534245")
        self.assertEqual(profile.nama_lengkap, "Fiqhi Deski Ismail")
        self.assertEqual(profile.jurusan, "IK")
        self.assertEqual(profile.angkatan, "2025")
        self.assertIsNone(profile.role)
        self.assertIsNone(profile.kelompok)

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

        self.assertFalse(Profile.objects.filter(user=self.user).exists())

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

    def test_anonymous_user_is_redirected_to_the_login_chooser(self):
        """Anonymous access should preserve the destination through the next query.

        Tujuannya halaman pemilih metode, bukan langsung CAS: sejak ada mentor
        non-SSO, user anonim di halaman ber-@login_required belum tentu punya
        akun SSO UI.
        """
        protected_url = reverse("siwak:mentee_feedback_history")

        response = self.client.get(protected_url)

        expected_login_url = reverse("siwak:login")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{expected_login_url}?next={protected_url}")

    def test_tugas_pages_redirect_non_mentee_to_landing_with_notice(self):
        """Tugas Mentoring: anonim / bukan Mentee dikembalikan ke /siwak dengan notifikasi."""
        tugas = Tugas.objects.create(
            judul_tugas="T", deskripsi="d", deadline=timezone.now() + datetime.timedelta(days=1)
        )
        urls = [reverse("siwak:tugas_list"), reverse("siwak:tugas_detail", args=[tugas.pk])]

        def assert_redirected(url):
            response = self.client.get(url, follow=True)
            self.assertEqual(response.redirect_chain[-1][0], reverse("siwak:landing"))
            self.assertContains(response, "Anda harus menjadi Mentee, hubungi CP SIWAK")

        for url in urls:
            assert_redirected(url)  # anonim
        self.client.force_login(User.objects.create_user(username="tanpa-role"))
        for url in urls:
            assert_redirected(url)  # login tapi role NULL
        mentor = User.objects.create_user(username="mentor")
        Profile.objects.create(user=mentor, npm="2100000001", role=Profile.ROLE_MENTOR)
        self.client.force_login(mentor)
        for url in urls:
            assert_redirected(url)  # mentor

    def test_mentee_can_open_tugas_list(self):
        mentee = User.objects.create_user(username="mentee")
        Profile.objects.create(user=mentee, npm="2500000001", role=Profile.ROLE_MENTEE)
        self.client.force_login(mentee)

        self.assertEqual(self.client.get(reverse("siwak:tugas_list")).status_code, 200)

    def test_navbar_shows_tugas_mentoring_only_for_mentee(self):
        link = f'href="{reverse("siwak:tugas_list")}"'
        self.assertNotContains(self.client.get(reverse("siwak:kelompok_search")), link)  # anonim
        mentor = User.objects.create_user(username="mentor")
        Profile.objects.create(user=mentor, npm="2100000002", role=Profile.ROLE_MENTOR)
        self.client.force_login(mentor)
        self.assertNotContains(self.client.get(reverse("siwak:kelompok_search")), link)
        mentee = User.objects.create_user(username="mentee")
        Profile.objects.create(user=mentee, npm="2500000002", role=Profile.ROLE_MENTEE)
        self.client.force_login(mentee)
        self.assertContains(self.client.get(reverse("siwak:kelompok_search")), link)

    def test_landing_cta_kumpulkan_tugas_only_once_and_only_for_mentee(self):
        cta = "Kumpulkan Tugas Mentoring"
        landing = reverse("siwak:landing")
        self.assertNotContains(self.client.get(landing), cta)  # anonim
        mentee = User.objects.create_user(username="mentee")
        Profile.objects.create(user=mentee, npm="2500000003", role=Profile.ROLE_MENTEE)
        self.client.force_login(mentee)
        self.assertContains(self.client.get(landing), cta, count=1)

    def test_tugas_pages_have_back_buttons(self):
        mentee = User.objects.create_user(username="mentee")
        Profile.objects.create(user=mentee, npm="2500000004", role=Profile.ROLE_MENTEE)
        tugas = Tugas.objects.create(
            judul_tugas="T", deskripsi="d", deadline=timezone.now() + datetime.timedelta(days=1)
        )
        self.client.force_login(mentee)

        daftar = self.client.get(reverse("siwak:tugas_list"))
        self.assertContains(daftar, f'href="{reverse("siwak:landing")}"')
        self.assertContains(daftar, 'aria-label="Kembali ke halaman SIWAK-NG"')
        detail = self.client.get(reverse("siwak:tugas_detail", args=[tugas.pk]))
        self.assertContains(detail, f'href="{reverse("siwak:tugas_list")}"')
        self.assertContains(detail, 'aria-label="Kembali ke daftar tugas"')

    def test_navbar_shows_panel_admin_only_for_staff(self):
        panel = reverse("siwak:panel_beranda")
        self.assertNotContains(self.client.get(reverse("siwak:landing")), f'href="{panel}"')
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.assertContains(self.client.get(reverse("siwak:landing")), f'href="{panel}"')

    def test_navbar_reads_the_profile_through_its_accessor(self):
        """Guard untuk `user.profil` di navbar.html.

        Template Django menelan atribut yang tidak ada tanpa melempar error, jadi
        salah ketik pada nama accessor ini tidak akan menggagalkan apa pun — link
        role-nya hanya hilang diam-diam. Ini yang membuatnya perlu diuji.
        """
        landing = reverse("siwak:landing")
        tugas = reverse("siwak:tugas_list")
        portal = reverse("siwak:mentor_dashboard")

        mentee = User.objects.create_user(username="navbar-mentee")
        Profile.objects.create(user=mentee, npm="2500000500", role=Profile.ROLE_MENTEE)
        self.client.force_login(mentee)
        halaman = self.client.get(landing)
        self.assertContains(halaman, f'href="{tugas}"')
        self.assertNotContains(halaman, f'href="{portal}"')

        mentor = User.objects.create_user(username="navbar-mentor")
        Profile.objects.create(user=mentor, npm="2100000500", role=Profile.ROLE_MENTOR)
        self.client.force_login(mentor)
        halaman = self.client.get(landing)
        self.assertContains(halaman, f'href="{portal}"')
        self.assertNotContains(halaman, f'href="{tugas}"')

class MentorLokalTests(TestCase):
    """Mentor non-SSO: akun dibuat pengelola di panel, login lewat form lokal.

    Regression guard yang penting di sini:
      * Jalur login lokal hanya untuk profil mentor ber-`auth_source="lokal"`.
        Mentee, staf, dan akun SSO tidak boleh lolos walau passwordnya benar.
      * Profil tanpa NPM disimpan sebagai NULL, bukan "", supaya dua mentor
        non-SSO tidak saling menabrak unique constraint.
      * Menghapus profilnya ikut menghapus akun loginnya — kalau tidak, User
        yatim tetap bisa login lalu mentok 403 di require_mentor.
      * Login CAS yang entah bagaimana mendarat di akun lokal harus ditolak,
        bukan menimpa identitasnya.
    """

    def setUp(self):
        self.pengurus = User.objects.create_user(username="pengurus", is_staff=True)
        self.client.force_login(self.pengurus)
        self.kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")

    def _tambah(self, nama="Kak Rahma", username="rahma", password="RahasiaKuat123", **extra):
        data = {
            "nama_lengkap": nama,
            "username": username,
            "password1": password,
            "password2": password,
            "akun_aktif": "on",
            "kelompok": self.kelompok.pk,
        }
        data.update(extra)
        return self.client.post(reverse("siwak:panel_tambah", args=["mentor_lokal"]), data)

    def test_panel_creates_the_profile_and_its_login_account_together(self):
        response = self._tambah()

        self.assertEqual(response.status_code, 302)
        profil = Profile.objects.get(nama_lengkap="Kak Rahma")
        self.assertEqual(profil.role, Profile.ROLE_MENTOR)
        self.assertEqual(profil.auth_source, Profile.SOURCE_LOKAL)
        self.assertIsNone(profil.npm)
        self.assertEqual(profil.kelompok, self.kelompok)

        akun = profil.user
        self.assertEqual(akun.username, "mentor-rahma")
        self.assertTrue(akun.check_password("RahasiaKuat123"))
        # Mentor bukan pengurus: panel SIWAK tetap tertutup untuknya.
        self.assertFalse(akun.is_staff)

    def test_two_mentors_without_npm_do_not_collide(self):
        """NPM disimpan NULL, bukan "" — dua NULL sah di bawah UNIQUE."""
        self._tambah(nama="Mentor Satu", username="satu")
        self._tambah(nama="Mentor Dua", username="dua")

        tanpa_npm = Profile.objects.filter(auth_source=Profile.SOURCE_LOKAL, npm__isnull=True)
        self.assertEqual(tanpa_npm.count(), 2)

    def test_username_gets_the_reserved_prefix_and_must_be_unique(self):
        self._tambah(username="mentor-rahma")  # sudah beranwalan, tidak digandakan
        self.assertTrue(User.objects.filter(username="mentor-rahma").exists())

        response = self._tambah(nama="Nama Lain", username="rahma")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(username="mentor-rahma").count(), 1)

    def test_a_local_mentor_can_log_in_and_lands_on_the_mentor_dashboard(self):
        self._tambah()
        self.client.logout()

        response = self.client.post(reverse("siwak:mentor_login"), {
            "username": "mentor-rahma", "password": "RahasiaKuat123",
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("siwak:mentor_dashboard"))

    def test_the_local_login_refuses_everyone_who_is_not_a_local_mentor(self):
        """Tanpa penyaring ini, setiap User berpassword valid bisa lewat sini."""
        mentee = User.objects.create_user(username="mentee", password="RahasiaKuat123")
        Profile.objects.create(user=mentee, npm="2500000100", role=Profile.ROLE_MENTEE)
        staf = User.objects.create_user(username="staf", password="RahasiaKuat123", is_staff=True)
        mentor_sso = User.objects.create_user(username="mentor-sso", password="RahasiaKuat123")
        Profile.objects.create(user=mentor_sso, npm="2100000100", role=Profile.ROLE_MENTOR)
        self.client.logout()

        for username in ("mentee", "staf", "mentor-sso"):
            with self.subTest(username=username):
                response = self.client.post(reverse("siwak:mentor_login"), {
                    "username": username, "password": "RahasiaKuat123",
                })
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_a_deactivated_account_cannot_log_in(self):
        self._tambah()
        User.objects.filter(username="mentor-rahma").update(is_active=False)
        self.client.logout()

        response = self.client.post(reverse("siwak:mentor_login"), {
            "username": "mentor-rahma", "password": "RahasiaKuat123",
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_editing_without_a_password_keeps_the_old_one(self):
        """Itu yang membuat halaman ubah sekaligus jadi reset password."""
        self._tambah()
        profil = Profile.objects.get(nama_lengkap="Kak Rahma")

        self.client.post(reverse("siwak:panel_ubah", args=["mentor_lokal", profil.pk]), {
            "nama_lengkap": "Kak Rahmawati",
            "username": "mentor-rahma",
            "password1": "",
            "password2": "",
            "akun_aktif": "on",
            "kelompok": self.kelompok.pk,
        })

        profil.refresh_from_db()
        self.assertEqual(profil.nama_lengkap, "Kak Rahmawati")
        self.assertTrue(profil.user.check_password("RahasiaKuat123"))

    def test_editing_with_a_password_replaces_it(self):
        self._tambah()
        profil = Profile.objects.get(nama_lengkap="Kak Rahma")

        self.client.post(reverse("siwak:panel_ubah", args=["mentor_lokal", profil.pk]), {
            "nama_lengkap": "Kak Rahma",
            "username": "mentor-rahma",
            "password1": "PasswordBaru456",
            "password2": "PasswordBaru456",
            "akun_aktif": "on",
            "kelompok": "",
        })

        profil.refresh_from_db()
        self.assertTrue(profil.user.check_password("PasswordBaru456"))

    def test_mismatched_password_confirmation_is_rejected(self):
        response = self._tambah(password="RahasiaKuat123", password2="BedaSendiri999")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Profile.objects.filter(nama_lengkap="Kak Rahma").exists())
        self.assertFalse(User.objects.filter(username="mentor-rahma").exists())

    def test_deleting_the_profile_also_deletes_its_login_account(self):
        self._tambah()
        profil = Profile.objects.get(nama_lengkap="Kak Rahma")

        # Pembersihannya dijadwalkan on_commit (lihat signals.py), dan TestCase
        # tidak pernah commit — jadi callback-nya dijalankan manual di sini.
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("siwak:panel_hapus", args=["mentor_lokal", profil.pk]))

        self.assertFalse(Profile.objects.filter(pk=profil.pk).exists())
        self.assertFalse(User.objects.filter(username="mentor-rahma").exists())

    def test_deleting_an_sso_profile_leaves_its_account_alone(self):
        """Akun SSO milik SSO UI, bukan milik panel."""
        akun = User.objects.create_user(username="mahasiswa")
        profil = Profile.objects.create(user=akun, npm="2500000200", role=Profile.ROLE_MENTEE)

        with self.captureOnCommitCallbacks(execute=True):
            profil.delete()

        self.assertTrue(User.objects.filter(pk=akun.pk).exists())

    def test_local_mentors_stay_out_of_the_sso_lists(self):
        """Daftar Mentor memakai MentorForm yang mewajibkan NPM, dan dropdown
        role di daftar Profile bisa mengunci mentor lokal keluar dari jalurnya."""
        self._tambah()
        profil = Profile.objects.get(nama_lengkap="Kak Rahma")

        for slug in ("mentor", "profil"):
            with self.subTest(slug=slug):
                # Diperiksa lewat isi halamannya, bukan HTML: notifikasi sukses
                # "… berhasil ditambahkan" ikut menyebut namanya di permintaan
                # berikutnya dan akan membuat pemeriksaan teks selalu gagal.
                response = self.client.get(reverse("siwak:panel_daftar", args=[slug]))
                self.assertNotIn(profil, response.context["halaman"].object_list)

    def test_the_local_mentor_list_shows_only_local_mentors(self):
        self._tambah()
        sso = Profile.objects.create(
            npm="2100000400", nama_lengkap="Mentor SSO", role=Profile.ROLE_MENTOR
        )

        response = self.client.get(reverse("siwak:panel_daftar", args=["mentor_lokal"]))

        isi = response.context["halaman"].object_list
        self.assertEqual([p.nama_lengkap for p in isi], ["Kak Rahma"])
        self.assertNotIn(sso, isi)

    def test_cas_login_refuses_to_land_on_a_local_account(self):
        self._tambah()
        akun = User.objects.get(username="mentor-rahma")

        with self.assertRaises(ValueError):
            handle_cas_login(
                sender=None, user=akun, username=akun.username,
                attributes={"npm": "2506000300", "nama": "Orang Lain", "kd_org": "01.00.12.01"},
            )

        profil = Profile.objects.get(user=akun)
        self.assertEqual(profil.nama_lengkap, "Kak Rahma")
        self.assertIsNone(profil.npm)

    def test_logout_follows_the_way_the_person_signed_in(self):
        """Akun lokal tidak punya sesi di sso.ui.ac.id, jadi tidak lewat CAS."""
        self._tambah()
        self.client.logout()
        self.client.post(reverse("siwak:mentor_login"), {
            "username": "mentor-rahma", "password": "RahasiaKuat123",
        })

        response = self.client.get(reverse("siwak:logout"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_logout_sends_cas_sessions_to_the_cas_logout(self):
        mahasiswa = User.objects.create_user(username="mahasiswa")
        self.client.force_login(mahasiswa, backend="django_cas_ng.backends.CASBackend")

        response = self.client.get(reverse("siwak:logout"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("siwak:cas_ng_logout"))

    def test_the_login_chooser_carries_the_next_destination_to_both_doors(self):
        """Tanpa ini deep link dari @login_required hilang saat metodenya dipilih."""
        self.client.logout()
        tujuan = reverse("siwak:mentor_dashboard")

        response = self.client.get(reverse("siwak:login"), {"next": tujuan})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'{reverse("siwak:cas_ng_login")}?next=')
        self.assertContains(response, f'{reverse("siwak:mentor_login")}?next=')

    def test_the_login_chooser_ignores_an_offsite_next(self):
        self.client.logout()

        response = self.client.get(reverse("siwak:login"), {"next": "https://jahat.example.com/"})

        self.assertNotContains(response, "jahat.example.com")

    def test_the_cp_link_comes_from_the_panel_and_falls_back_when_empty(self):
        """CP-nya diatur pengelola lewat SiwakInfo, bukan ditulis di template."""
        self.client.logout()

        info = SiwakInfo.get_solo()
        info.kontak_cp = "https://wa.me/6281200000000"
        info.save()
        self.assertContains(self.client.get(reverse("siwak:login")), info.kontak_cp)

        # Belum diisi: tautannya jatuh ke Hubungi Kami, bukan jadi teks mati.
        info.kontak_cp = ""
        info.save()
        response = self.client.get(reverse("siwak:login"))
        self.assertContains(response, f'href="{reverse("hubungi_kami")}"')


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
            reverse("siwak:panel_bagian", args=["mentoring"]),
            reverse("siwak:panel_daftar", args=["sesi"]),
            reverse("siwak:panel_daftar", args=["aspek"]),
            reverse("siwak:panel_daftar", args=["tugas"]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_unknown_data_type_returns_not_found(self):
        """A made-up resource slug must not fall through to a server error."""
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))

        response = self.client.get(reverse("siwak:panel_daftar", args=["ngawur"]))

        self.assertEqual(response.status_code, 404)


class PanelPesertaTests(TestCase):
    """Verify the participant and mentor forms write identity, role and group in one step."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")

    def test_adding_a_participant_creates_a_mentee_profile_with_its_group(self):
        """One submitted form should produce the profile, its role and its group."""
        response = self.client.post(reverse("siwak:panel_tambah", args=["peserta"]), {
            "nama_lengkap": "Marwa Muhlashon",
            "npm": "2506000009",
            "jurusan": "SI",
            "angkatan": "2025",
            "kelompok": self.kelompok.pk,
        })

        self.assertEqual(response.status_code, 302)
        profil = Profile.objects.get(npm="2506000009")
        self.assertEqual(profil.nama_lengkap, "Marwa Muhlashon")
        self.assertEqual(profil.role, Profile.ROLE_MENTEE)
        self.assertEqual(profil.kelompok, self.kelompok)

    def test_participant_without_group_is_still_recorded(self):
        """Leaving the group empty should still register the student as a mentee."""
        self.client.post(reverse("siwak:panel_tambah", args=["peserta"]), {
            "nama_lengkap": "Belum Ditempatkan",
            "npm": "2506000010",
            "jurusan": "IK",
            "angkatan": "",
            "kelompok": "",
        })

        profil = Profile.objects.get(npm="2506000010")
        self.assertIsNone(profil.kelompok)
        self.assertEqual(profil.role, Profile.ROLE_MENTEE)

    def test_a_participant_still_needs_a_jurusan(self):
        """`jurusan` is optional on the model (prepared mentors have none yet),
        but "Cari Kelompok" finds mentees by it, so the mentee form requires it."""
        response = self.client.post(reverse("siwak:panel_tambah", args=["peserta"]), {
            "nama_lengkap": "Tanpa Jurusan",
            "npm": "2506000012",
            "jurusan": "",
            "kelompok": "",
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Profile.objects.filter(npm="2506000012").exists())

    def test_adding_a_mentor_creates_a_mentor_profile(self):
        """Mentors can be prepared with only a name and NPM, before they ever log in."""
        response = self.client.post(reverse("siwak:panel_tambah", args=["mentor"]), {
            "nama_lengkap": "Kak Zaid",
            "npm": "2106000001",
            "kelompok": self.kelompok.pk,
        })

        self.assertEqual(response.status_code, 302)
        profil = Profile.objects.get(npm="2106000001")
        self.assertEqual(profil.role, Profile.ROLE_MENTOR)
        self.assertEqual(profil.kelompok, self.kelompok)
        self.assertEqual(profil.jurusan, "")
        self.assertIsNone(profil.user)

    def test_deleting_a_participant_removes_the_profile_but_not_the_group(self):
        profil = Profile.objects.create(
            npm="2506000011", nama_lengkap="Hapus Aku", jurusan="KA", kelompok=self.kelompok,
            role=Profile.ROLE_MENTEE,
        )

        self.client.post(reverse("siwak:panel_hapus", args=["peserta", profil.pk]))

        self.assertFalse(Profile.objects.filter(pk=profil.pk).exists())
        self.assertTrue(KelompokMentoring.objects.filter(pk=self.kelompok.pk).exists())

    def test_mentors_and_participants_cannot_be_reached_through_each_others_pages(self):
        """Both lists are the same table now; each page must stay inside its role."""
        mentee = Profile.objects.create(
            npm="2506000013", nama_lengkap="Si Mentee", jurusan="IK", role=Profile.ROLE_MENTEE
        )
        mentor = Profile.objects.create(
            npm="2106000002", nama_lengkap="Si Mentor", role=Profile.ROLE_MENTOR
        )

        for slug, pk in (("peserta", mentor.pk), ("mentor", mentee.pk)):
            with self.subTest(slug=slug, pk=pk):
                self.assertEqual(
                    self.client.get(reverse("siwak:panel_ubah", args=[slug, pk])).status_code, 404
                )
                self.assertEqual(
                    self.client.post(reverse("siwak:panel_hapus", args=[slug, pk])).status_code, 404
                )

        self.assertTrue(Profile.objects.filter(pk=mentee.pk).exists())
        self.assertTrue(Profile.objects.filter(pk=mentor.pk).exists())

    def test_each_list_only_shows_its_own_role(self):
        Profile.objects.create(
            npm="2506000014", nama_lengkap="Si Mentee", jurusan="IK", role=Profile.ROLE_MENTEE
        )
        Profile.objects.create(
            npm="2106000003", nama_lengkap="Si Mentor", role=Profile.ROLE_MENTOR
        )

        def nama(slug):
            response = self.client.get(reverse("siwak:panel_daftar", args=[slug]))
            return [baris["obj"].nama_lengkap for baris in response.context["baris"]]

        self.assertEqual(nama("peserta"), ["Si Mentee"])
        self.assertEqual(nama("mentor"), ["Si Mentor"])

    def test_menu_and_dashboard_counts_are_split_by_role(self):
        Profile.objects.create(
            npm="2506000015", nama_lengkap="Mentee", jurusan="IK", role=Profile.ROLE_MENTEE
        )
        Profile.objects.create(
            npm="2106000004", nama_lengkap="Mentor", role=Profile.ROLE_MENTOR,
            kelompok=self.kelompok,
        )

        menu = self.client.get(reverse("siwak:panel_bagian", args=["kelompok"]))
        jumlah = {butir["label"]: butir["jumlah"] for butir in menu.context["butir"]}
        self.assertEqual(jumlah["Mentee"], 1)
        self.assertEqual(jumlah["Mentor"], 1)

        beranda = self.client.get(reverse("siwak:panel_beranda"))
        self.assertEqual(
            dict(beranda.context["ringkasan"]),
            {
                "Mentee": 1,
                "Kelompok mentoring": 1,
                "Mentor": 1,
                "Belum punya kelompok": 1,
            },
        )


class PanelProfilTests(TestCase):
    """Verify the Profile list and the role dropdown that feeds Mentee/Mentor."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")
        self.profil = Profile.objects.create(
            npm="2506000040", nama_lengkap="Belum Ditentukan", jurusan="IK"
        )
        self.url_role = reverse("siwak:panel_set_role", args=[self.profil.pk])

    def _daftar(self, slug):
        return self.client.get(reverse("siwak:panel_daftar", args=[slug]))

    def _role(self):
        self.profil.refresh_from_db()
        return self.profil.role

    def test_new_profiles_have_no_role(self):
        """NULL, not a silent default to mentee."""
        self.assertIsNone(self.profil.role)

    def test_a_profile_without_a_role_is_in_neither_role_list(self):
        for slug in ("peserta", "mentor"):
            with self.subTest(slug=slug):
                self.assertEqual(self._daftar(slug).context["baris"], [])

    def test_the_profile_list_shows_everyone_with_a_running_number(self):
        Profile.objects.create(
            npm="2506000041", nama_lengkap="Sudah Mentee", jurusan="SI",
            role=Profile.ROLE_MENTEE,
        )
        Profile.objects.create(
            npm="2106000041", nama_lengkap="Sudah Mentor", role=Profile.ROLE_MENTOR,
        )

        response = self._daftar("profil")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([b["sel"][0]["nilai"] for b in response.context["baris"]], [1, 2, 3])
        self.assertEqual(
            [k["judul"] for k in response.context["kepala"]], ["No", "Nama", "NPM", "Role"]
        )

    def test_the_running_number_continues_across_pages(self):
        for i in range(30):
            Profile.objects.create(npm=f"26000001{i:02d}", nama_lengkap=f"Orang {i:02d}")

        response = self.client.get(reverse("siwak:panel_daftar", args=["profil"]), {"page": 2})

        self.assertEqual(response.context["baris"][0]["sel"][0]["nilai"], 26)

    def test_the_profile_list_is_display_only(self):
        """Identity comes from SSO; only the role is editable, via the dropdown."""
        self.assertEqual(
            self.client.get(reverse("siwak:panel_tambah", args=["profil"])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse("siwak:panel_ubah", args=["profil", self.profil.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.post(reverse("siwak:panel_hapus", args=["profil", self.profil.pk])).status_code, 404
        )
        response = self._daftar("profil")
        sumber = response.context["sumber_data"]
        # Tidak ada Ubah/Hapus; satu-satunya tombol baris adalah "Buat RSVP".
        self.assertFalse(sumber.boleh_ubah or sumber.boleh_hapus)
        self.assertEqual([a.nama_url for a in sumber.aksi_baris], ["siwak:panel_profil_rsvp"])
        self.assertNotContains(response, "panel_ubah")
        self.assertNotContains(response, ">Hapus<")

    def test_the_dropdown_offers_mentee_and_mentor(self):
        response = self._daftar("profil")

        self.assertContains(response, 'name="role"')
        self.assertContains(response, '<option value="mentee"')
        self.assertContains(response, '<option value="mentor"')

    def test_the_role_dropdown_asks_for_confirmation_before_saving(self):
        """Like the RSVP switch: a role decides access, so no one-click save."""
        response = self._daftar("profil")

        self.assertContains(response, "Ubah role profil ini?")
        self.assertContains(response, "Belum Ditentukan")  # the row's name, in the dialog
        self.assertContains(response, "Ya, ubah")
        self.assertContains(response, "@change=")
        # It must not also carry the auto-submit handler the plain dropdowns use.
        self.assertNotContains(response, 'onchange="this.form.submit()"')

    def test_the_group_dropdowns_still_save_without_asking(self):
        """Only the role dropdown got the dialog; moving groups stays one step."""
        self.profil.role = Profile.ROLE_MENTEE
        self.profil.save()

        response = self._daftar("peserta")

        self.assertContains(response, 'onchange="this.form.submit()"')
        self.assertNotContains(response, "Ya, ubah")

    def test_picking_mentee_moves_the_profile_to_the_mentee_list(self):
        self.client.post(self.url_role, {"role": "mentee"})

        self.assertEqual(self._role(), Profile.ROLE_MENTEE)
        nama = [b["obj"].nama_lengkap for b in self._daftar("peserta").context["baris"]]
        self.assertEqual(nama, ["Belum Ditentukan"])
        self.assertEqual(self._daftar("mentor").context["baris"], [])

    def test_picking_mentor_moves_the_profile_to_the_mentor_list(self):
        self.client.post(self.url_role, {"role": "mentor"})

        self.assertEqual(self._role(), Profile.ROLE_MENTOR)
        nama = [b["obj"].nama_lengkap for b in self._daftar("mentor").context["baris"]]
        self.assertEqual(nama, ["Belum Ditentukan"])

    def test_changing_role_releases_the_group(self):
        """`kelompok` means a seat for a mentee but a post for a mentor, so it
        must not silently carry over."""
        self.profil.role = Profile.ROLE_MENTEE
        self.profil.kelompok = self.kelompok
        self.profil.save()

        self.client.post(self.url_role, {"role": "mentor"})

        self.profil.refresh_from_db()
        self.assertEqual(self.profil.role, Profile.ROLE_MENTOR)
        self.assertIsNone(self.profil.kelompok)
        self.assertEqual(self.kelompok.daftar_mentor.count(), 0)

    def test_picking_the_same_role_again_keeps_the_group(self):
        self.profil.role = Profile.ROLE_MENTEE
        self.profil.kelompok = self.kelompok
        self.profil.save()

        self.client.post(self.url_role, {"role": "mentee"})

        self.profil.refresh_from_db()
        self.assertEqual(self.profil.kelompok, self.kelompok)

    def test_the_empty_choice_clears_the_role(self):
        self.client.post(self.url_role, {"role": "mentee"})

        self.client.post(self.url_role, {"role": ""})

        self.assertIsNone(self._role())

    def test_an_unknown_role_is_rejected(self):
        self.client.post(self.url_role, {"role": "admin"})

        self.assertIsNone(self._role())

    def test_only_staff_may_change_a_role(self):
        self.client.force_login(User.objects.create_user(username="biasa"))

        response = self.client.post(self.url_role, {"role": "mentee"})

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self._role())

    def test_changing_a_role_over_get_is_refused(self):
        self.assertEqual(self.client.get(self.url_role).status_code, 405)

    def test_a_profile_without_a_role_cannot_be_placed_in_a_group(self):
        self.client.post(
            reverse("siwak:panel_set_kelompok", args=[self.profil.pk]),
            {"kelompok": str(self.kelompok.pk)},
        )

        self.profil.refresh_from_db()
        self.assertIsNone(self.profil.kelompok)

    def test_a_role_less_profile_gets_no_mentee_or_mentor_access(self):
        """The whole point of NULL: nothing is granted until staff decide."""
        user = User.objects.create_user(username="2506000040")
        self.profil.user = user
        self.profil.save()
        self.client.force_login(user)

        tugas = Tugas.objects.create(
            judul_tugas="T", deskripsi="d", deadline=timezone.now() + datetime.timedelta(days=1)
        )

        response = self.client.get(reverse("siwak:tugas_detail", args=[tugas.pk]))
        self.assertRedirects(response, reverse("siwak:landing"))
        self.assertEqual(self.client.get(reverse("siwak:mentor_dashboard")).status_code, 403)

    def test_the_sidebar_order_is_profile_mentee_mentor_group(self):
        response = self._daftar("profil")

        bagian = next(m for m in response.context["menu"] if m["bagian"].slug == "kelompok")
        self.assertEqual(
            [b["label"] for b in bagian["butir"]],
            ["Profile", "Mentee", "Mentor", "Mentor Non-SSO", "Kelompok Mentoring"],
        )


class PanelRelasiTests(TestCase):
    """Verify the list-page dropdowns rewrite a profile's group."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.k1 = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")
        self.k2 = KelompokMentoring.objects.create(nama_kelompok="Kelompok 2")
        self.maba = Profile.objects.create(
            npm="2506000020", nama_lengkap="Pindah Aku", jurusan="IK", kelompok=self.k1,
            role=Profile.ROLE_MENTEE,
        )
        self.url_kelompok = reverse("siwak:panel_set_kelompok", args=[self.maba.pk])

    def _mentor(self, nama, npm, kelompok=None):
        return Profile.objects.create(
            npm=npm, nama_lengkap=nama, role=Profile.ROLE_MENTOR, kelompok=kelompok
        )

    def test_the_dropdown_moves_a_mentee_to_another_group(self):
        """Picking another group in the participant list should relocate them."""
        self.client.post(self.url_kelompok, {"kelompok": str(self.k2.pk)})

        self.maba.refresh_from_db()
        self.assertEqual(self.maba.kelompok, self.k2)

    def test_the_empty_choice_takes_the_mentee_out_of_every_group(self):
        """The blank option should leave the student unplaced, not unchanged."""
        self.client.post(self.url_kelompok, {"kelompok": ""})

        self.maba.refresh_from_db()
        self.assertIsNone(self.maba.kelompok)

    def test_a_student_without_a_group_can_be_placed(self):
        """Staff-registered students start unplaced and get a group later."""
        baru = Profile.objects.create(
            npm="2506000022", nama_lengkap="Baru Didaftarkan", jurusan="SI", role=Profile.ROLE_MENTEE
        )

        self.client.post(
            reverse("siwak:panel_set_kelompok", args=[baru.pk]),
            {"kelompok": str(self.k1.pk)},
        )

        baru.refresh_from_db()
        self.assertEqual(baru.kelompok, self.k1)

    def test_moving_one_mentee_leaves_the_other_rows_alone(self):
        """Editing a single row must never touch the rest of the list."""
        lain = Profile.objects.create(
            npm="2506000021", nama_lengkap="Peserta Lain", jurusan="SI", kelompok=self.k1,
            role=Profile.ROLE_MENTEE,
        )

        self.client.post(self.url_kelompok, {"kelompok": str(self.k2.pk)})

        lain.refresh_from_db()
        self.assertEqual(lain.kelompok, self.k1)

    def test_the_mentor_dropdown_sets_the_group_and_keeps_the_role(self):
        """The mentor page has one dropdown; it writes the same column the mentee one does."""
        mentor = self._mentor("Kak Fatimah", "2106000010")

        self.client.post(
            reverse("siwak:panel_set_kelompok", args=[mentor.pk]),
            {"kelompok": str(self.k2.pk)},
        )

        mentor.refresh_from_db()
        self.assertEqual(mentor.kelompok, self.k2)
        self.assertEqual(mentor.role, Profile.ROLE_MENTOR)

    def test_the_mentor_dropdown_can_release_the_group(self):
        """The blank option means "holds nothing", not "leave it as it was"."""
        mentor = self._mentor("Kak Fatimah", "2106000010", self.k2)

        self.client.post(
            reverse("siwak:panel_set_kelompok", args=[mentor.pk]), {"kelompok": ""}
        )

        mentor.refresh_from_db()
        self.assertIsNone(mentor.kelompok)

    def test_a_mentor_never_holds_two_groups_at_once(self):
        """The group is one column, so moving a mentor really empties the group
        they left."""
        mentor = self._mentor("Kak Fatimah", "2106000010", self.k1)

        self.client.post(
            reverse("siwak:panel_set_kelompok", args=[mentor.pk]),
            {"kelompok": str(self.k2.pk)},
        )

        mentor.refresh_from_db()
        self.assertEqual(mentor.kelompok, self.k2)
        self.assertEqual(self.k1.daftar_mentor.count(), 0)

    def test_a_group_may_still_hold_several_mentors(self):
        """The rule runs one way only: one group per mentor, not one mentor per group."""
        satu = self._mentor("Kak Ahmad", "2106000011")
        dua = self._mentor("Kak Fatimah", "2106000012")

        for mentor in (satu, dua):
            self.client.post(
                reverse("siwak:panel_set_kelompok", args=[mentor.pk]),
                {"kelompok": str(self.k1.pk)},
            )

        self.assertEqual(self.k1.daftar_mentor.count(), 2)

    def test_the_mentor_and_mentee_dropdowns_post_to_the_same_endpoint(self):
        """Both are Profile, so the list must not invent a second route."""
        mentor = self._mentor("Kak Fatimah", "2106000010")

        for slug, profil in (("peserta", self.maba), ("mentor", mentor)):
            with self.subTest(slug=slug):
                response = self.client.get(reverse("siwak:panel_daftar", args=[slug]))
                # By type, not "first cell with a url": the mentor list also has
                # an NPM editor with its own endpoint.
                dropdown = next(
                    s for s in response.context["baris"][0]["sel"]
                    if s["tipe"].startswith("pilih_kelompok")
                )
                self.assertEqual(
                    dropdown["url"], reverse("siwak:panel_set_kelompok", args=[profil.pk])
                )

    def test_a_mentor_placement_returns_to_the_mentor_list_by_default(self):
        mentor = self._mentor("Kak Fatimah", "2106000010")

        response = self.client.post(
            reverse("siwak:panel_set_kelompok", args=[mentor.pk]),
            {"kelompok": str(self.k2.pk)},
        )

        self.assertEqual(response.url, reverse("siwak:panel_daftar", args=["mentor"]))

    def test_group_capacity_counts_mentees_and_never_mentors(self):
        """"Kelompok 1 (1/15)" is about seats for mentees; a mentor holding the
        group must not use one up."""
        self._mentor("Kak Ahmad", "2106000011", self.k1)
        self._mentor("Kak Fatimah", "2106000012", self.k1)

        response = self.client.get(reverse("siwak:panel_daftar", args=["peserta"]))
        terisi = {k["label"]: k["detail"] for k in response.context["daftar_kelompok"]}
        self.assertEqual(terisi["Kelompok 1"], "1/15")

        response = self.client.get(reverse("siwak:panel_daftar", args=["kelompok"]))
        baris = next(b for b in response.context["baris"] if b["obj"] == self.k1)
        cell = {s["judul"]: s["nilai"] for s in baris["sel"]}
        self.assertEqual(cell["Mentee"], "1 / 15")
        self.assertEqual(cell["Mentor"], "Kak Ahmad, Kak Fatimah")

    def test_editing_a_relation_over_get_is_refused(self):
        """This route changes data, so a plain link must not be able to fire it."""
        self.assertEqual(self.client.get(self.url_kelompok).status_code, 405)

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


class KelompokSearchTests(TestCase):
    """Verify the public "Cari Kelompok" lookup finds mentees and shows their mentors."""

    def setUp(self):
        self.url = reverse("siwak:kelompok_search")
        self.kelompok = KelompokMentoring.objects.create(
            nama_kelompok="Kelompok 7", link_grup="https://chat.whatsapp.com/contoh"
        )
        Profile.objects.create(
            npm="2506000050", nama_lengkap="Aisyah Putri", jurusan="IK", kelompok=self.kelompok,
            role=Profile.ROLE_MENTEE,
        )
        Profile.objects.create(
            npm="2106000050", nama_lengkap="Kak Ahmad", jurusan="IK",
            role=Profile.ROLE_MENTOR, kelompok=self.kelompok,
        )

    def _cari(self, nama):
        return self.client.post(self.url, {"nama_lengkap": nama})

    def test_a_mentee_finds_their_group_and_its_mentors(self):
        response = self._cari("aisyah putri")

        self.assertEqual(response.context["result_state"], "found")
        self.assertContains(response, "Kelompok 7")
        self.assertContains(response, "Kak Ahmad")
        self.assertContains(response, "https://chat.whatsapp.com/contoh")

    def test_a_mentee_can_find_their_group_by_npm(self):
        response = self._cari("2506000050")

        self.assertEqual(response.context["result_state"], "found")
        self.assertEqual(response.context["peserta"].nama_lengkap, "Aisyah Putri")
        self.assertContains(response, "Kelompok 7")

    def test_search_form_has_no_jurusan_field(self):
        self.assertNotIn("jurusan", CariKelompokForm().fields)
        response = self.client.get(self.url)
        self.assertNotContains(response, 'name="jurusan"')

    def test_name_or_npm_alone_is_enough_to_submit(self):
        response = self._cari("Aisyah Putri")

        self.assertTrue(response.context["form"].is_valid())
        self.assertEqual(response.context["result_state"], "found")

    def test_blank_input_is_rejected(self):
        response = self._cari("")

        self.assertFalse(response.context["form"].is_valid())
        self.assertIsNone(response.context["result_state"])

    def test_npm_match_wins_over_a_same_named_mentee(self):
        Profile.objects.create(
            npm="2506000099", nama_lengkap="2506000050", jurusan="SI", role=Profile.ROLE_MENTEE
        )

        response = self._cari("2506000050")

        self.assertEqual(response.context["peserta"].npm, "2506000050")

    def test_a_mentor_is_not_found_as_if_they_were_a_participant(self):
        response = self._cari("Kak Ahmad")

        self.assertEqual(response.context["result_state"], "not_found")

    def test_a_mentee_without_a_group_is_told_so(self):
        Profile.objects.create(
            npm="2506000051", nama_lengkap="Belum Ada", jurusan="SI", role=Profile.ROLE_MENTEE
        )

        response = self._cari("Belum Ada")

        self.assertEqual(response.context["result_state"], "no_group_yet")


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
        Profile.objects.create(
            npm=npm, nama_lengkap=nama, jurusan="IK", kelompok=kelompok, role=Profile.ROLE_MENTEE
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
        Profile.objects.create(
            npm="2106000021", nama_lengkap="Kak Ahmad",
            role=Profile.ROLE_MENTOR, kelompok=self.k10,
        )
        Profile.objects.create(
            npm="2106000022", nama_lengkap="Kak Zaid",
            role=Profile.ROLE_MENTOR, kelompok=self.k2,
        )

        response = self.client.get(
            reverse("siwak:panel_daftar", args=["mentor"]), {"urut": "kelompok"}
        )

        self.assertEqual(
            [baris["obj"].nama_lengkap for baris in response.context["baris"]],
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


class PanelRsvpPencarianTests(TestCase):
    """Verify the search box on the RSVP list of one event."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.event = SiwakEvent.objects.create(judul="Main Event", rsvp_dibuka=True)
        self.url = reverse("siwak:panel_rsvp", args=[self.event.pk])
        self.budi = self._rsvp("2306000001", "Budi Santoso")
        self.citra = self._rsvp("2306000002", "Citra Lestari")

    def _rsvp(self, npm, nama, event=None):
        user = User.objects.create_user(username=npm)
        Profile.objects.create(user=user, npm=npm, nama_lengkap=nama, jurusan="IK")
        return EventRSVP.objects.create(event=event or self.event, user=user)

    def _nama(self, response):
        return [
            r.user.profil.nama_lengkap
            for r in response.context["halaman"].object_list
        ]

    def test_searching_by_name_keeps_only_the_matching_participants(self):
        response = self.client.get(self.url, {"q": "citra"})

        self.assertEqual(self._nama(response), ["Citra Lestari"])

    def test_searching_by_npm_works_too(self):
        """Panitia at the door reads the NPM off a card, not the full name."""
        response = self.client.get(self.url, {"q": "2306000001"})

        self.assertEqual(self._nama(response), ["Budi Santoso"])

    def test_a_participant_without_a_profile_is_still_searchable(self):
        """SSO may not have filled the profile yet; the username is the fallback."""
        user = User.objects.create_user(username="tamu-khusus")
        EventRSVP.objects.create(event=self.event, user=user)

        response = self.client.get(self.url, {"q": "tamu"})

        self.assertEqual(
            [r.user.username for r in response.context["halaman"].object_list],
            ["tamu-khusus"],
        )

    def test_the_search_never_reaches_into_another_event(self):
        """Two events may well share the same participants."""
        lain = SiwakEvent.objects.create(judul="Acara Lain")
        self._rsvp("2306000003", "Citra Kembar", event=lain)

        response = self.client.get(self.url, {"q": "citra"})

        self.assertEqual(self._nama(response), ["Citra Lestari"])

    def test_the_summary_still_counts_every_participant_of_the_event(self):
        """The tiles describe the event, so a search must not shrink them."""
        self.budi.status_kehadiran = "hadir"
        self.budi.save()

        response = self.client.get(self.url, {"q": "citra"})

        self.assertEqual(
            response.context["ringkasan_rsvp"],
            [("Total RSVP", 2), ("Sudah check-in", 1), ("Kupon ditukar", 0), ("Menunggu login", 0)],
        )

    def test_an_empty_search_shows_everyone_again(self):
        response = self.client.get(self.url, {"q": "   "})

        self.assertEqual(self._nama(response), ["Budi Santoso", "Citra Lestari"])

    def test_the_export_follows_the_search(self):
        """Otherwise the downloaded file differs from what is on screen."""
        response = self.client.get(
            reverse("siwak:panel_rsvp_csv", args=[self.event.pk]), {"q": "citra"}
        )

        isi = response.content.decode("utf-8")
        self.assertIn("Citra Lestari", isi)
        self.assertNotIn("Budi Santoso", isi)

    def test_a_status_change_returns_to_the_search_results(self):
        """The dropdowns post `next`, so a correction must not drop the filter."""
        halaman = f"{self.url}?q=citra"
        response = self.client.post(
            reverse("siwak:panel_rsvp_status", args=[self.citra.pk]),
            {"medan": "kehadiran", "nilai": "hadir", "next": halaman},
        )

        self.assertRedirects(response, halaman)

class QrcodeServiceTests(TestCase):
    """Unit tests for the signing/QR helpers (PRD 10 - Signed QR token)."""

    def setUp(self):
        self.host_user = User.objects.create_user(username="maba")
        self.rsvp = EventRSVP.objects.create(
            event=SiwakEvent.objects.create(judul="Main Event"), user=self.host_user,
        )

    def test_sign_unsign_roundtrip(self):
        payload = sign_payload("registrasi", self.rsvp.qr_registrasi_token)
        self.assertEqual(unsign_payload(payload),
                         {"kind": "registrasi", "token": self.rsvp.qr_registrasi_token})

    def test_unsign_rejects_tampered_token(self):
        payload = sign_payload("registrasi", self.rsvp.qr_registrasi_token)
        # Flip one character inside the signed payload: signature must break.
        tampered = payload[:-1] + ("0" if payload[-1] != "0" else "1")
        with self.assertRaises(signing.BadSignature):
            unsign_payload(tampered)

    def test_unsign_rejects_expired_signature(self):
        old_ts = int(time.time()) - 31 * 24 * 3600  # 31 days ago (> 30-day max_age)
        signed = self._signed_with_timestamp(
            {"kind": "registrasi", "token": self.rsvp.qr_registrasi_token},
            old_ts,
        )
        with self.assertRaises(signing.SignatureExpired):
            unsign_payload(signed)

    def test_qr_data_uri_is_an_encoded_png(self):
        uri = registrasi_qr_data_uri(self._request(), self.rsvp)
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        image_bytes = base64.b64decode(uri.split(",", 1)[1])
        self.assertTrue(image_bytes.startswith(b"\x89PNG"))

    def test_rsvp_page_sings_both_kinds(self):
        # The two QR helpers must target different tokens so a registrasi QR
        # never redeems a meal kupon and vice versa.
        reg = registrasi_qr_data_uri(self._request(), self.rsvp)
        kup = kupon_qr_data_uri(self._request(), self.rsvp)
        self.assertNotEqual(reg, kup)

    def test_distinct_rsvps_produce_distinct_qrs(self):
        other = EventRSVP.objects.create(
            event=SiwakEvent.objects.create(judul="Event Lain"),
            user=User.objects.create_user(username="maba-lain"),
        )
        self.assertNotEqual(
            registrasi_qr_data_uri(self._request(), self.rsvp),
            registrasi_qr_data_uri(self._request(), other),
        )

    @staticmethod
    def _signed_with_timestamp(payload, timestamp):
        """Forge a *valid* signed value stamped at `timestamp` (seconds).

        Django's signer joins parts with `:`, not `.`, and the middle segment
        is a base62 Unix timestamp.
        """
        from django.core.signing import b62_encode

        b64 = signing.b64_encode(signing.JSONSerializer().dumps(payload))
        new = f"{b64}:{b62_encode(timestamp)}"
        signer = signing.Signer(salt=SIGNING_SALT)
        return f"{new}:{signer.signature(new)}"

    @staticmethod
    def _request():
        from django.test import RequestFactory
        return RequestFactory().get("/")


class RSVPViewTests(TestCase):
    """PRD 5.2 — the RSVP flow itself."""

    def setUp(self):
        self.user = User.objects.create_user(username="2506534245")
        Profile.objects.create(
            user=self.user, npm="2506534245", nama_lengkap="Fiqhi Deski Ismail", jurusan="IK",
        )
        self.staff = User.objects.create_user(username="panitia", is_staff=True)
        self.admin = User.objects.create_superuser(username="admin", password="x")
        self.event = SiwakEvent.objects.create(judul="Main Event SIWAK", rsvp_dibuka=True)
        self.closed_event = SiwakEvent.objects.create(judul="Closed Event", rsvp_dibuka=False)
        self.url = reverse("siwak:rsvp", args=[self.event.id])
        self.valid_npm = "2506534245"

    # -- access control -----------------------------------------------------

    def test_anonymous_is_redirected_to_login_with_next(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)
        self.assertIn(self.url, response.url)

    def test_anonymous_and_nonexistent_event_is_redirected_not_404(self):
        # The view comments claim a missing event yields 404 even without a
        # login, but @login_required runs first: anonymous users are sent to
        # the login page for *any* destination, deleted events included.
        url = reverse("siwak:rsvp", args=[99999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    # -- the form round trip ------------------------------------------------

    def test_browser_post_without_npm_creates_rsvp(self):
        # `npm` is rendered with the HTML `disabled` attribute, so a browser
        # never submits it. Because the field is disabled, Django substitutes
        # its `initial` (the SSO profile NPM) — the RSVP is created with the
        # user's own NPM anyway. (This used to be documented as broken; it is
        # actually usable.)
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"kehadiran": "hadir", "npm": ""})
        self.assertEqual(response.status_code, 302)
        rsvp = EventRSVP.objects.get(event=self.event, user=self.user)
        self.assertEqual(rsvp.kehadiran, "hadir")

    def test_post_with_npm_creates_rsvp_and_redirects(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"kehadiran": "hadir", "npm": self.valid_npm})
        self.assertEqual(response.status_code, 302)
        rsvp = EventRSVP.objects.get(event=self.event, user=self.user)
        self.assertEqual(rsvp.kehadiran, "hadir")
        self.assertEqual(rsvp.status_kehadiran, "belum_hadir")  # new enum
        self.assertEqual(rsvp.status_kupon, "unused")
        self.assertTrue(rsvp.qr_registrasi_token)
        self.assertTrue(rsvp.qr_kupon_token)

    def test_izin_requires_alasan(self):
        self.client.force_login(self.user)
        response = self.client.post(
            self.url, {"kehadiran": "izin", "npm": self.valid_npm, "alasan_izin": ""}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alasan izin wajib diisi")
        self.assertFalse(EventRSVP.objects.filter(event=self.event).exists())

    def test_izin_with_alasan_succeeds(self):
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            {"kehadiran": "izin", "npm": self.valid_npm, "alasan_izin": "Acara keluarga"},
        )
        self.assertEqual(response.status_code, 302)
        rsvp = EventRSVP.objects.get(event=self.event, user=self.user)
        self.assertEqual(rsvp.kehadiran, "izin")
        self.assertEqual(rsvp.alasan_izin, "Acara keluarga")

    def test_second_post_is_ignored_after_rsvp_exists(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"kehadiran": "hadir", "npm": self.valid_npm})
        EventRSVP.objects.update(kehadiran="izin", alasan_izin="awal")

        # A later POST must not change the stored RSVP.
        response = self.client.post(self.url, {"kehadiran": "izin", "npm": self.valid_npm})
        self.assertEqual(response.status_code, 200)
        rsvp = EventRSVP.objects.get(event=self.event, user=self.user)
        self.assertEqual(rsvp.kehadiran, "izin")
        self.assertEqual(EventRSVP.objects.filter(event=self.event).count(), 1)

    # -- closed events ------------------------------------------------------

    def test_closed_event_blocks_new_rsvp(self):
        self.client.force_login(self.user)
        url = reverse("siwak:rsvp", args=[self.closed_event.id])
        response = self.client.post(url, {"kehadiran": "hadir", "npm": self.valid_npm})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RSVP Telah Ditutup")
        self.assertFalse(EventRSVP.objects.filter(event=self.closed_event).exists())

    def test_existing_rsvp_still_shows_qr_when_event_closed(self):
        rsvp = EventRSVP.objects.create(event=self.closed_event, user=self.user)
        self.client.force_login(self.user)
        response = self.client.get(reverse("siwak:rsvp", args=[self.closed_event.id]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "RSVP Telah Ditutup")
        self.assertContains(response, "QR RSVP")
        self.assertContains(response, "data:image/png;base64,")

    def test_rsvp_button_shown_on_landing_and_detail_when_open(self):
        rsvp_url = reverse("siwak:rsvp", args=[self.event.id])
        landing = self.client.get(reverse("siwak:landing"))
        self.assertContains(landing, f'href="{rsvp_url}"')
        self.assertContains(landing, "Isi RSVP Main Event SIWAK")
        detail = self.client.get(reverse("siwak:event_detail", args=[self.event.id]))
        self.assertContains(detail, f'href="{rsvp_url}"')
        self.assertContains(detail, "Isi RSVP Main Event SIWAK")

    def test_rsvp_button_hidden_on_landing_and_detail_when_closed(self):
        rsvp_url = reverse("siwak:rsvp", args=[self.closed_event.id])
        landing = self.client.get(reverse("siwak:landing"))
        self.assertNotContains(landing, f'href="{rsvp_url}"')
        self.assertNotContains(landing, "Isi RSVP Closed Event")
        detail = self.client.get(reverse("siwak:event_detail", args=[self.closed_event.id]))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, f'href="{rsvp_url}"')
        self.assertNotContains(detail, "Isi RSVP Closed Event")

    # -- QR presence --------------------------------------------------------

    def test_rsvp_page_exposes_both_qr_data_uris(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"kehadiran": "hadir", "npm": self.valid_npm})
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "QR Kehadiran")
        self.assertContains(response, "QR Kupon Makan")


class QRVerifyAccessControlTests(TestCase):
    """PRD 6.x — qr_verify must be strictly admin-only."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="admin", password="x")
        self.staff = User.objects.create_user(username="panitia", is_staff=True)
        self.regular = User.objects.create_user(username="maba")
        self.event = SiwakEvent.objects.create(judul="Main Event")
        self.rsvp = EventRSVP.objects.create(event=self.event, user=self.regular)
        self.signed = sign_payload("registrasi", self.rsvp.qr_registrasi_token)
        self.url = reverse("siwak:qr_verify", args=[self.signed])

    def test_anonymous_redirects_to_admin_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)
        self.assertIn(self.url, unquote(response.url))

    def test_staff_but_not_superuser_is_forbidden(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_regular_user_is_forbidden(self):
        self.client.force_login(self.regular)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_superuser_is_allowed(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


class QRVerifyScanTests(TestCase):
    """PRD 6.1 / 6.2 — check-in and kupon redemption through the scan page.

    GET only renders a confirmation page (read-only). The mutation happens on
    a CSRF-protected POST — this closes the "<img src=...> flips attendance"
    hole.
    """

    def setUp(self):
        self.admin = User.objects.create_superuser(username="admin", password="x")
        self.attendant = User.objects.create_user(username="hadir-user")
        self.no_show = User.objects.create_user(username="tidak-hadir-user")
        self.event = SiwakEvent.objects.create(judul="Main Event")

        self.rsvp_hadir = EventRSVP.objects.create(
            event=self.event, user=self.attendant, kehadiran="hadir",
        )
        self.rsvp_tidak = EventRSVP.objects.create(
            event=self.event, user=self.no_show, kehadiran="tidak_hadir",
        )

        self.reg_signed = sign_payload("registrasi", self.rsvp_hadir.qr_registrasi_token)
        self.kupon_signed = sign_payload("kupon", self.rsvp_hadir.qr_kupon_token)

        self.client.force_login(self.admin)

    def reg_url(self):
        return reverse("siwak:qr_verify", args=[self.reg_signed])

    def kupon_url(self):
        return reverse("siwak:qr_verify", args=[self.kupon_signed])

    # -- confirm step ---------------------------------------------------------

    def test_get_only_renders_confirm_page_and_never_mutates(self):
        # The whole point of the redesign: a plain GET (e.g. an <img> tag in
        # an admin's browser) must leave attendance state untouched.
        response = self.client.get(self.reg_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Konfirmasi Check-in")
        self.assertContains(response, "csrfmiddlewaretoken")
        self.rsvp_hadir.refresh_from_db()
        self.assertEqual(self.rsvp_hadir.status_kehadiran, "belum_hadir")
        self.assertIsNone(self.rsvp_hadir.checked_in_at)

    def test_get_requires_confirmation_for_kupon_too(self):
        response = self.client.get(self.kupon_url())
        self.assertContains(response, "Konfirmasi Tukar Kupon")
        self.rsvp_hadir.refresh_from_db()
        self.assertEqual(self.rsvp_hadir.status_kupon, "unused")

    def test_post_without_csrf_token_is_rejected(self):
        # CSRF protection is enforced on the mutation itself.
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.post(self.reg_url())
        self.assertEqual(response.status_code, 403)
        self.rsvp_hadir.refresh_from_db()
        self.assertEqual(self.rsvp_hadir.status_kehadiran, "belum_hadir")

    # -- registrasi check-in -------------------------------------------------

    def test_first_scan_checks_in_and_records_time(self):
        response = self.client.post(self.reg_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Check-in Berhasil")
        self.rsvp_hadir.refresh_from_db()
        self.assertEqual(self.rsvp_hadir.status_kehadiran, "hadir")
        self.assertIsNotNone(self.rsvp_hadir.checked_in_at)

    def test_second_scan_reports_already_and_keeps_original_time(self):
        self.client.post(self.reg_url())
        self.rsvp_hadir.refresh_from_db()
        original_time = self.rsvp_hadir.checked_in_at

        response = self.client.post(self.reg_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sudah Check-in")
        self.rsvp_hadir.refresh_from_db()
        self.assertEqual(self.rsvp_hadir.checked_in_at, original_time)

    # -- kupon redemption ----------------------------------------------------

    def test_first_scan_redeems_kupon(self):
        response = self.client.post(self.kupon_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kupon Berhasil Ditukar")
        self.rsvp_hadir.refresh_from_db()
        self.assertEqual(self.rsvp_hadir.status_kupon, "redeemed")
        self.assertIsNotNone(self.rsvp_hadir.redeemed_at)

    def test_second_scan_cannot_redeem_twice(self):
        self.client.post(self.kupon_url())
        response = self.client.post(self.kupon_url())
        self.assertContains(response, "Sudah Ditukar")
        self.rsvp_hadir.refresh_from_db()
        self.assertEqual(self.rsvp_hadir.status_kupon, "redeemed")

    def test_kupon_result_card_shows_redemption_time_not_checkin_time(self):
        # The kupon card must show the kupon's *own* timestamp (redeemed_at),
        # not fall back to the registrasi check-in time when the participant
        # already checked in earlier.
        self.client.post(self.reg_url())
        self.rsvp_hadir.refresh_from_db()
        checkin_label = "Check-in " + formats.date_format(
            timezone.localtime(self.rsvp_hadir.checked_in_at), "j F Y, H:i"
        ) + " WIB"

        response = self.client.post(self.kupon_url())

        self.rsvp_hadir.refresh_from_db()
        redeem_label = "Ditukar " + formats.date_format(
            timezone.localtime(self.rsvp_hadir.redeemed_at), "j F Y, H:i"
        ) + " WIB"
        self.assertContains(response, redeem_label)
        self.assertNotContains(response, checkin_label)

    def test_registrasi_and_kupon_tokens_do_not_interfere(self):
        # A registrasi signature pointing at a kupon token must not redeem:
        mixed = sign_payload("registrasi", self.rsvp_hadir.qr_kupon_token)
        response = self.client.post(reverse("siwak:qr_verify", args=[mixed]))
        self.assertContains(response, "Data RSVP tidak ditemukan")
        self.rsvp_hadir.refresh_from_db()
        self.assertEqual(self.rsvp_hadir.status_kupon, "unused")  # untouched

    # -- error paths ---------------------------------------------------------

    def test_bad_signature_shows_invalid_error(self):
        response = self.client.get(
            reverse("siwak:qr_verify", args=["not-a-valid-signature"])
        )
        self.assertContains(response, "QR tidak valid atau rusak.")

    def test_unknown_token_shows_not_found(self):
        bogus = sign_payload("registrasi", "0" * 64)
        response = self.client.get(reverse("siwak:qr_verify", args=[bogus]))
        self.assertContains(response, "Data RSVP tidak ditemukan.")

    def test_expired_signature_shows_expired_error(self):
        old_ts = int(time.time()) - 31 * 24 * 3600
        expired = QrcodeServiceTests._signed_with_timestamp(
            {"kind": "registrasi", "token": self.rsvp_hadir.qr_registrasi_token},
            old_ts,
        )
        response = self.client.get(reverse("siwak:qr_verify", args=[expired]))
        self.assertContains(response, "QR sudah kedaluwarsa.")
        self.rsvp_hadir.refresh_from_db()
        self.assertEqual(self.rsvp_hadir.status_kehadiran, "belum_hadir")

    # -- kehadiran gate (no-show / izin must not be marked present) ----------

    def test_no_show_rsvp_cannot_be_checked_in(self):
        signed = sign_payload("registrasi", self.rsvp_tidak.qr_registrasi_token)
        response = self.client.post(reverse("siwak:qr_verify", args=[signed]))
        self.assertContains(response, "Check-in ditolak")
        self.rsvp_tidak.refresh_from_db()
        self.assertEqual(self.rsvp_tidak.kehadiran, "tidak_hadir")
        self.assertEqual(self.rsvp_tidak.status_kehadiran, "belum_hadir")


class EventRSVPModelTests(TestCase):
    """Model invariants for the new hadir / belum_hadir enum."""

    def setUp(self):
        self.event = SiwakEvent.objects.create(judul="Main Event")
        self.user = User.objects.create_user(username="maba")

    def test_defaults(self):
        rsvp = EventRSVP.objects.create(event=self.event, user=self.user)
        self.assertEqual(rsvp.status_kehadiran, "belum_hadir")
        self.assertEqual(rsvp.status_kupon, "unused")
        self.assertEqual(rsvp.kehadiran, "hadir")

    def test_tokens_are_unique_and_generated(self):
        rsvp = EventRSVP.objects.create(event=self.event, user=self.user)
        self.assertTrue(rsvp.qr_registrasi_token)
        self.assertTrue(rsvp.qr_kupon_token)
        self.assertNotEqual(rsvp.qr_registrasi_token, rsvp.qr_kupon_token)
        self.assertEqual(
            EventRSVP.objects.filter(qr_registrasi_token=rsvp.qr_registrasi_token).count(),
            1,
        )

    def test_choices_are_constrained_to_new_enum(self):
        valid = {choice for choice, _ in EventRSVP.KEHADIRAN_STATUS_CHOICES}
        self.assertEqual(valid, {"hadir", "belum_hadir"})

    def test_unique_together_prevents_duplicate_rsvp(self):
        EventRSVP.objects.create(event=self.event, user=self.user)
        with self.assertRaises(Exception):
            EventRSVP.objects.create(event=self.event, user=self.user)


class PanelSesiTests(TestCase):
    """Verify mentoring sessions can be edited but never added or deleted."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")
        self.sesi = MentoringSession.objects.filter(kelompok=self.kelompok).first()

    def test_creating_a_group_already_fills_the_session_list(self):
        """The list should show the four sessions the signal created."""
        response = self.client.get(reverse("siwak:panel_daftar", args=["sesi"]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(MentoringSession.objects.filter(kelompok=self.kelompok).count(), 4)

    def test_the_list_offers_no_way_to_add_a_session(self):
        """Sessions are created by the signal, so the add button must be gone."""
        response = self.client.get(reverse("siwak:panel_daftar", args=["sesi"]))

        self.assertNotContains(response, reverse("siwak:panel_tambah", args=["sesi"]))

    def test_the_add_page_is_not_reachable_by_url(self):
        """Hiding the button is not enough; the address must refuse too."""
        response = self.client.get(reverse("siwak:panel_tambah", args=["sesi"]))

        self.assertEqual(response.status_code, 404)

    def test_deleting_a_session_over_its_own_url_is_refused(self):
        """A hand-made POST must not remove a session the signal owns."""
        response = self.client.post(reverse("siwak:panel_hapus", args=["sesi", self.sesi.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(MentoringSession.objects.filter(pk=self.sesi.pk).exists())

    def test_editing_a_session_saves_the_date_and_activates_it(self):
        """Activating a session here is what unlocks the mentor's presensi form."""
        response = self.client.post(
            reverse("siwak:panel_ubah", args=["sesi", self.sesi.pk]),
            {"tanggal": "2026-09-20", "catatan": "Ruang 3113", "is_active": "on"},
        )

        self.assertEqual(response.status_code, 302)
        self.sesi.refresh_from_db()
        self.assertTrue(self.sesi.is_active)
        self.assertEqual(self.sesi.catatan, "Ruang 3113")
        self.assertEqual(str(self.sesi.tanggal), "2026-09-20")

    def test_editing_a_session_never_moves_it_to_another_group(self):
        """The group is locked, otherwise the (kelompok, nomor) pair could collide."""
        lain = KelompokMentoring.objects.create(nama_kelompok="Kelompok 2")

        self.client.post(
            reverse("siwak:panel_ubah", args=["sesi", self.sesi.pk]),
            {"tanggal": "", "catatan": "", "kelompok": lain.pk, "nomor": 4},
        )

        self.sesi.refresh_from_db()
        self.assertEqual(self.sesi.kelompok, self.kelompok)
        self.assertEqual(self.sesi.nomor, 1)

    def test_the_list_can_activate_a_session_without_opening_the_form(self):
        """Opening the next session for every group is the job done most here."""
        response = self.client.post(
            reverse("siwak:panel_sesi_aktif", args=[self.sesi.pk]), {"aktif": "1"}
        )

        self.assertEqual(response.status_code, 302)
        self.sesi.refresh_from_db()
        self.assertTrue(self.sesi.is_active)

    def test_the_same_dropdown_switches_a_session_back_off(self):
        """A saklar that only works one way would still need the edit form."""
        MentoringSession.objects.filter(pk=self.sesi.pk).update(is_active=True)

        self.client.post(
            reverse("siwak:panel_sesi_aktif", args=[self.sesi.pk]), {"aktif": "0"}
        )

        self.sesi.refresh_from_db()
        self.assertFalse(self.sesi.is_active)

    def test_switching_lands_back_on_the_page_it_was_used_from(self):
        """Sort order lives in the address, so saving must not reset it."""
        asal = f"{reverse('siwak:panel_daftar', args=['sesi'])}?urut=tanggal&arah=turun"

        response = self.client.post(
            reverse("siwak:panel_sesi_aktif", args=[self.sesi.pk]),
            {"aktif": "1", "next": asal},
        )

        self.assertRedirects(response, asal)

    def test_switching_over_a_get_is_refused(self):
        """Like every other panel mutation, this one is POST-only."""
        response = self.client.get(reverse("siwak:panel_sesi_aktif", args=[self.sesi.pk]))

        self.assertEqual(response.status_code, 405)


class PanelAspekTests(TestCase):
    """Verify the assessment rubric can be managed without breaking saved scores.

    Migrasi 0013 sudah mengisi tiga aspek bawaan, jadi tes di sini memakai nama
    lain dan tidak pernah menganggap tabelnya kosong.
    """

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))

    def test_adding_an_aspect_makes_it_available_to_mentors(self):
        """A new aspect should become part of the rubric straight away."""
        response = self.client.post(
            reverse("siwak:panel_tambah", args=["aspek"]),
            {"nama": "Kedisiplinan", "urutan": 4, "is_active": "on"},
        )

        self.assertEqual(response.status_code, 302)
        aspek = AssessmentAspect.objects.get(nama="Kedisiplinan")
        self.assertTrue(aspek.is_active)

    def test_a_duplicate_aspect_name_is_refused_in_plain_language(self):
        """The rubric already ships with "Keaktifan"; adding it twice must not 500."""
        response = self.client.post(
            reverse("siwak:panel_tambah", args=["aspek"]),
            {"nama": "Keaktifan", "urutan": 9, "is_active": "on"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sudah ada aspek penilaian dengan nama ini.")
        self.assertEqual(AssessmentAspect.objects.filter(nama="Keaktifan").count(), 1)

    def test_an_unused_aspect_can_still_be_deleted(self):
        """Nothing protects an aspect nobody has scored against yet."""
        aspek = AssessmentAspect.objects.create(nama="Salah Ketik")

        self.client.post(reverse("siwak:panel_hapus", args=["aspek", aspek.pk]))

        self.assertFalse(AssessmentAspect.objects.filter(pk=aspek.pk).exists())

    def test_deleting_a_scored_aspect_explains_itself_instead_of_crashing(self):
        """MenteeAssessment protects the aspect, so the panel must say why."""
        aspek = AssessmentAspect.objects.get(nama="Kehadiran")
        kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 1")
        peserta = Profile.objects.create(
            npm="2506000030", nama_lengkap="Peserta Dinilai", jurusan="IK", kelompok=kelompok
        )
        MenteeAssessment.objects.create(peserta=peserta, aspect=aspek, score=80)

        response = self.client.post(
            reverse("siwak:panel_hapus", args=["aspek", aspek.pk]), follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(AssessmentAspect.objects.filter(pk=aspek.pk).exists())
        self.assertContains(response, "masih dipakai data lain")


class PanelTugasDaftarTests(TestCase):
    """Verify the task list stays down to the two controls pengurus asked for."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.tugas = Tugas.objects.create(
            judul_tugas="Tugas Uji", deskripsi="Isi", deadline=timezone.now()
        )

    def test_the_row_leads_to_the_question_builder(self):
        """Menyusun pertanyaan tetap satu klik dari daftar tugas."""
        response = self.client.get(reverse("siwak:panel_daftar", args=["tugas"]))

        self.assertContains(response, reverse("siwak:panel_pertanyaan", args=[self.tugas.pk]))

    def test_the_row_offers_the_answer_viewer(self):
        """Pengurus dapat membuka submission dari daftar tugas."""
        response = self.client.get(reverse("siwak:panel_daftar", args=["tugas"]))

        self.assertContains(response, reverse("siwak:panel_jawaban", args=[self.tugas.pk]))

    def test_neither_short_list_carries_a_search_box(self):
        """Tugas dan aspek penilaian isinya sedikit; kotak cari cuma jadi bising."""
        for slug in ("tugas", "aspek"):
            with self.subTest(slug=slug):
                response = self.client.get(reverse("siwak:panel_daftar", args=[slug]))

                self.assertNotContains(response, 'type="search"')

    def test_the_rubric_list_drops_internal_columns(self):
        """Urutan dan jumlah pemakaian tidak perlu dilihat pengurus."""
        response = self.client.get(reverse("siwak:panel_daftar", args=["aspek"]))

        self.assertNotContains(response, "Dipakai")
        self.assertNotContains(response, "Urutan")


class PanelPertanyaanTests(TestCase):
    """Verify the task question builder: ordering, choice rules, and cleanup."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.tugas = Tugas.objects.create(
            judul_tugas="Tugas Uji", deskripsi="Isi", deadline=timezone.now()
        )

    def _tambah(self, teks, tipe="text", **ekstra):
        data = {
            "pertanyaan": teks,
            "tipe": tipe,
            "choices-TOTAL_FORMS": "0",
            "choices-INITIAL_FORMS": "0",
            "choices-MIN_NUM_FORMS": "0",
            "choices-MAX_NUM_FORMS": "1000",
        }
        data.update(ekstra)
        return self.client.post(
            reverse("siwak:panel_pertanyaan_tambah", args=[self.tugas.pk]), data
        )

    def test_a_text_question_is_added_to_the_end_of_the_list(self):
        """Each new question should queue up after the ones already there."""
        self._tambah("Pertanyaan satu")
        self._tambah("Pertanyaan dua")

        urutan = list(
            self.tugas.questions.order_by("urutan", "pk").values_list("pertanyaan", flat=True)
        )
        self.assertEqual(urutan, ["Pertanyaan satu", "Pertanyaan dua"])

    def test_a_multiple_choice_question_needs_at_least_two_options(self):
        """One option is not a choice, so the form must refuse it."""
        response = self._tambah(
            "Pilih satu",
            tipe="choice",
            **{
                "choices-TOTAL_FORMS": "1",
                "choices-0-teks": "Cuma ini",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Question.objects.exists())
        self.assertContains(response, "minimal dua pilihan")

    def test_a_multiple_choice_question_saves_its_options(self):
        """Two filled options is the smallest valid multiple choice question."""
        response = self._tambah(
            "Materi favorit",
            tipe="choice",
            **{
                "choices-TOTAL_FORMS": "2",
                "choices-0-teks": "Tauhid",
                "choices-1-teks": "Fiqih",
            },
        )

        self.assertEqual(response.status_code, 302)
        soal = Question.objects.get(pertanyaan="Materi favorit")
        self.assertEqual(
            list(soal.choices.order_by("pk").values_list("teks", flat=True)),
            ["Tauhid", "Fiqih"],
        )

    def test_switching_away_from_choice_clears_the_orphaned_options(self):
        """A text question must not keep options that can never be shown."""
        soal = Question.objects.create(
            tugas=self.tugas, pertanyaan="Dulu pilihan ganda", tipe="choice"
        )
        Choice.objects.create(question=soal, teks="A")
        Choice.objects.create(question=soal, teks="B")

        self.client.post(
            reverse("siwak:panel_pertanyaan_ubah", args=[soal.pk]),
            {
                "pertanyaan": "Sekarang isian teks",
                "tipe": "text",
                "choices-TOTAL_FORMS": "0",
                "choices-INITIAL_FORMS": "2",
                "choices-MIN_NUM_FORMS": "0",
                "choices-MAX_NUM_FORMS": "1000",
            },
        )

        soal.refresh_from_db()
        self.assertEqual(soal.tipe, "text")
        self.assertEqual(soal.choices.count(), 0)

    def test_the_arrows_swap_two_questions_that_both_start_at_zero(self):
        """Rows made outside the panel all sit at urutan=0; the swap must still work."""
        satu = Question.objects.create(tugas=self.tugas, pertanyaan="Satu", tipe="text")
        dua = Question.objects.create(tugas=self.tugas, pertanyaan="Dua", tipe="text")
        self.assertEqual(satu.urutan, dua.urutan)

        self.client.post(reverse("siwak:panel_pertanyaan_urut", args=[dua.pk]), {"arah": "naik"})

        urutan = list(
            self.tugas.questions.order_by("urutan", "pk").values_list("pertanyaan", flat=True)
        )
        self.assertEqual(urutan, ["Dua", "Satu"])

    def test_the_first_question_cannot_be_moved_further_up(self):
        """Moving past the edge should be a no-op, not an error."""
        satu = Question.objects.create(tugas=self.tugas, pertanyaan="Satu", tipe="text")
        Question.objects.create(tugas=self.tugas, pertanyaan="Dua", tipe="text")

        self.client.post(reverse("siwak:panel_pertanyaan_urut", args=[satu.pk]), {"arah": "naik"})

        urutan = list(
            self.tugas.questions.order_by("urutan", "pk").values_list("pertanyaan", flat=True)
        )
        self.assertEqual(urutan, ["Satu", "Dua"])

    def test_reordering_over_get_is_refused(self):
        """Order changes are POST-only, like every other panel mutation."""
        soal = Question.objects.create(tugas=self.tugas, pertanyaan="Satu", tipe="text")

        response = self.client.get(reverse("siwak:panel_pertanyaan_urut", args=[soal.pk]))

        self.assertEqual(response.status_code, 405)

    def test_deleting_a_question_closes_the_gap_it_leaves(self):
        """Remaining questions should renumber so the arrows keep working."""
        self._tambah("Satu")
        self._tambah("Dua")
        self._tambah("Tiga")
        kedua = Question.objects.get(pertanyaan="Dua")

        self.client.post(reverse("siwak:panel_pertanyaan_hapus", args=[kedua.pk]))

        self.assertEqual(
            list(self.tugas.questions.order_by("urutan").values_list("urutan", flat=True)),
            [0, 1],
        )


class PanelJawabanTests(TestCase):
    """Verify the read-only answer viewer scopes, searches, and exports correctly."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.tugas = Tugas.objects.create(
            judul_tugas="Tugas Refleksi", deskripsi="Isi", deadline=timezone.now()
        )
        self.soal = Question.objects.create(
            tugas=self.tugas, pertanyaan="Apa kesanmu?", tipe="text", urutan=0
        )
        self.maba = self._peserta("Aisyah Putri", "2506000040")
        self.lain = self._peserta("Bilal Rahman", "2506000041")

    def _peserta(self, nama, npm):
        user = User.objects.create_user(username=npm)
        Profile.objects.create(
            user=user, npm=npm, nama_lengkap=nama, jurusan="IK"
        )
        return user

    def _kumpul(self, user, isi):
        pengumpulan = TugasSubmission.objects.create(tugas=self.tugas, user=user)
        Answer.objects.create(submission=pengumpulan, question=self.soal, text_answer=isi)
        return pengumpulan

    def test_the_page_lists_every_submission_with_its_answer(self):
        """Each row should carry the student's own answer text."""
        self._kumpul(self.maba, "Seru sekali")

        response = self.client.get(reverse("siwak:panel_jawaban", args=[self.tugas.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aisyah Putri")
        self.assertContains(response, "Seru sekali")

    def test_searching_by_name_keeps_only_the_matching_student(self):
        """The search narrows the list without hiding the answer content."""
        self._kumpul(self.maba, "Jawaban Aisyah")
        self._kumpul(self.lain, "Jawaban Bilal")

        response = self.client.get(
            reverse("siwak:panel_jawaban", args=[self.tugas.pk]), {"q": "Aisyah"}
        )

        self.assertContains(response, "Aisyah Putri")
        self.assertNotContains(response, "Bilal Rahman")

    def test_searching_by_npm_works_too(self):
        """Pengurus usually have the NPM, not the spelling of the name."""
        self._kumpul(self.maba, "Jawaban Aisyah")
        self._kumpul(self.lain, "Jawaban Bilal")

        response = self.client.get(
            reverse("siwak:panel_jawaban", args=[self.tugas.pk]), {"q": "2506000041"}
        )

        self.assertContains(response, "Bilal Rahman")
        self.assertNotContains(response, "Aisyah Putri")

    def test_the_search_never_reaches_into_another_task(self):
        """Submissions belonging to a different task must stay out of this page."""
        lain = Tugas.objects.create(
            judul_tugas="Tugas Lain", deskripsi="x", deadline=timezone.now()
        )
        TugasSubmission.objects.create(tugas=lain, user=self.maba)

        response = self.client.get(reverse("siwak:panel_jawaban", args=[self.tugas.pk]))

        self.assertEqual(len(response.context["baris"]), 0)

    def test_the_export_returns_a_csv_with_one_column_per_question(self):
        """The header must line up with the questions in their shown order."""
        self._kumpul(self.maba, "Seru sekali")

        response = self.client.get(reverse("siwak:panel_jawaban_csv", args=[self.tugas.pk]))

        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment;", response["Content-Disposition"])
        isi = response.content.decode()
        self.assertIn("Apa kesanmu?", isi.splitlines()[0])
        self.assertIn("Seru sekali", isi)

    def test_the_export_follows_the_active_search(self):
        """Downloading a filtered view should not quietly return everyone."""
        self._kumpul(self.maba, "Jawaban Aisyah")
        self._kumpul(self.lain, "Jawaban Bilal")

        response = self.client.get(
            reverse("siwak:panel_jawaban_csv", args=[self.tugas.pk]), {"q": "Aisyah"}
        )

        isi = response.content.decode()
        self.assertIn("Aisyah Putri", isi)
        self.assertNotIn("Bilal Rahman", isi)

    def test_the_viewer_offers_no_way_to_change_an_answer(self):
        """Submitted answers are an audit record, so the page stays read-only."""
        self._kumpul(self.maba, "Seru sekali")

        response = self.client.get(reverse("siwak:panel_jawaban", args=[self.tugas.pk]))

        # Tidak ada isian apa pun yang terikat ke jawaban, jadi tidak ada yang
        # bisa dikirim balik untuk mengubahnya.
        self.assertNotContains(response, 'name="text_answer"')
        self.assertNotContains(response, 'name="selected_choice"')


class TugasUploadTests(TestCase):
    """Pengumpulan tugas (semua isian = Question), otorisasi, dan lifecycle storage."""

    def setUp(self):
        self.enterContext(override_settings(STORAGES={
            "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }))
        self.user = User.objects.create_user(username="upload-mentee")
        self.group = KelompokMentoring.objects.create(nama_kelompok="Upload group")
        self.profile = Profile.objects.create(
            user=self.user, npm="2600000001", nama_lengkap="Mentee Upload",
            role=Profile.ROLE_MENTEE, kelompok=self.group,
        )
        self.tugas = Tugas.objects.create(
            judul_tugas="Tugas Upload", deskripsi="Kumpulkan jawaban.",
            deadline=timezone.now() + datetime.timedelta(days=1), max_file_size_mb=1,
        )
        self.url = reverse("siwak:tugas_detail", args=[self.tugas.pk])
        self.client.force_login(self.user)

    def upload(self, name="tugas.pdf", content=b"%PDF-1.7\ncontoh"):
        return SimpleUploadedFile(name, content)

    def submit(self, **data):
        return self.client.post(self.url, data)

    def submission(self):
        return TugasSubmission.objects.get(tugas=self.tugas, user=self.user)

    def text_question(self):
        return Question.objects.create(tugas=self.tugas, pertanyaan="Refleksi", tipe="text")

    def file_question(self):
        return Question.objects.create(tugas=self.tugas, pertanyaan="Lampiran", tipe="file")

    def submit_text(self, value="Jawaban"):
        question = self.text_question()
        return self.submit(**{f"question_{question.pk}": value})

    def questions(self):
        text = self.text_question()
        choice = Question.objects.create(tugas=self.tugas, pertanyaan="Pilihan", tipe="choice")
        option = Choice.objects.create(question=choice, teks="Setuju")
        file = self.file_question()
        return text, choice, option, file

    def test_task_without_questions_has_no_fields_and_cannot_be_submitted(self):
        page = self.client.get(self.url)
        self.assertEqual(len(page.context["form"].fields), 0)
        self.assertFalse(page.context["can_submit"])
        self.assertNotContains(page, "Upload File")
        self.assertNotContains(page, ">Submit</button>")
        self.assertRedirects(self.submit(), self.url)
        self.assertFalse(TugasSubmission.objects.exists())

    def test_valid_extensions_are_saved(self):
        question = self.file_question()
        for extension in ("pdf", "docx", "jpg", "jpeg", "png", "PDF"):
            with self.subTest(extension=extension):
                response = self.submit(**{f"question_{question.pk}": self.upload(f"tugas.{extension}")})
                self.assertRedirects(response, self.url)
                file = self.submission().answers.get().file_answer
                self.assertTrue(file.storage.exists(file.name))
                self.assertEqual(self.submission().status, "submitted")
        self.assertEqual(TugasSubmission.objects.count(), 1)

    def test_extension_and_size_are_validated_on_server(self):
        question = self.file_question()
        for name, content, error in (
            ("tugas.exe", b"executable", "Format file tidak didukung"),
            ("tugas", b"no extension", "Format file tidak didukung"),
            ("tugas.pdf", b"x" * (1024 * 1024 + 1), "Ukuran file melebihi batas 1 MB"),
        ):
            with self.subTest(name=name):
                response = self.submit(**{f"question_{question.pk}": self.upload(name, content)})
                self.assertContains(response, error)
                self.assertFalse(TugasSubmission.objects.exists())

    def test_file_exactly_at_limit_is_accepted(self):
        question = self.file_question()
        response = self.submit(**{f"question_{question.pk}": self.upload(content=b"x" * 1024 * 1024)})
        self.assertEqual(response.status_code, 302)

    def test_first_submission_after_deadline_is_late(self):
        question = self.text_question()
        self.tugas.deadline = timezone.now() - datetime.timedelta(seconds=1)
        self.tugas.save()
        page = self.client.get(self.url)
        self.assertTrue(page.context["can_submit"])
        self.assertEqual(self.submit(**{f"question_{question.pk}": "Telat"}).status_code, 302)
        self.assertEqual(self.submission().status, "late")

    def test_at_deadline_is_submitted(self):
        with patch("siwak.models.timezone.now", return_value=self.tugas.deadline):
            self.assertEqual(self.submit_text().status_code, 302)
        self.assertEqual(self.submission().status, "submitted")

    def test_resubmit_updates_timestamp_status_and_answer(self):
        question = self.text_question()
        self.submit(**{f"question_{question.pk}": "Lama"})
        previous = self.submission()
        TugasSubmission.objects.filter(pk=previous.pk).update(
            submitted_at=timezone.now() - datetime.timedelta(hours=1), status="late"
        )
        self.assertEqual(self.submit(**{f"question_{question.pk}": "Baru"}).status_code, 302)
        current = self.submission()
        self.assertEqual(current.pk, previous.pk)
        self.assertGreater(current.submitted_at, previous.submitted_at)
        self.assertEqual(current.status, "submitted")
        self.assertEqual(current.answers.get().text_answer, "Baru")

    def test_resubmit_after_deadline_is_rejected(self):
        question = self.text_question()
        self.submit(**{f"question_{question.pk}": "Lama"})
        previous = self.submission()
        self.tugas.deadline = timezone.now() - datetime.timedelta(seconds=1)
        self.tugas.save()
        response = self.submit(**{f"question_{question.pk}": "Baru"})
        self.assertEqual(response.status_code, 302)
        current = self.submission()
        self.assertEqual(current.submitted_at, previous.submitted_at)
        self.assertEqual(current.answers.get().text_answer, "Lama")
        self.assertFalse(self.client.get(self.url).context["can_submit"])

    def test_submitted_page_allows_editing_with_file_placeholder(self):
        text, choice, option, file = self.questions()
        data = {f"question_{text.pk}": "Refleksi lama", f"question_{choice.pk}": option.pk,
                f"question_{file.pk}": self.upload("lampiran.pdf")}
        self.assertEqual(self.submit(**data).status_code, 302)
        submission = self.submission()
        answer = submission.answers.get(question=file)
        page = self.client.get(self.url)
        self.assertNotContains(page, "Upload File")
        self.assertNotContains(page, ">Submit</button>")
        self.assertContains(page, "Ganti File")
        self.assertContains(page, "Simpan Perubahan")
        self.assertContains(page, "Refleksi lama")
        self.assertContains(page, "Setuju")
        self.assertContains(page, answer.file_answer.name.rsplit("/", 1)[-1])
        self.assertContains(page, reverse("siwak:answer_download", args=[submission.pk, answer.pk]))

    def test_answers_are_prefilled_and_files_can_be_retained(self):
        text, choice, option, file = self.questions()
        data = {f"question_{text.pk}": "Refleksi lama", f"question_{choice.pk}": option.pk,
                f"question_{file.pk}": self.upload("lampiran.pdf")}
        self.assertEqual(self.submit(**data).status_code, 302)
        submission = self.submission()
        form = self.client.get(self.url).context["form"]
        self.assertEqual(form[f"question_{text.pk}"].value(), "Refleksi lama")
        self.assertEqual(form[f"question_{choice.pk}"].value(), option.pk)
        self.assertTrue(form[f"question_{file.pk}"].value())
        old_file = submission.answers.get(question=file).file_answer.name
        response = self.client.post(self.url, {
            f"question_{text.pk}": "Refleksi baru", f"question_{choice.pk}": option.pk,
        })
        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.answers.get(question=text).text_answer, "Refleksi baru")
        self.assertEqual(submission.answers.get(question=file).file_answer.name, old_file)

    def test_invalid_dynamic_answers_do_not_create_submission(self):
        text, choice, option, file = self.questions()
        data = {f"question_{text.pk}": "Refleksi", f"question_{choice.pk}": option.pk}
        for upload in (self.upload("bad.exe"), self.upload(content=b"x" * (1024 * 1024 + 1))):
            response = self.submit(**data, **{f"question_{file.pk}": upload})
            self.assertTrue(response.context["form"].errors)
            self.assertFalse(TugasSubmission.objects.exists())
            self.assertFalse(Answer.objects.exists())
        response = self.submit()
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(TugasSubmission.objects.exists())

    def test_only_authenticated_mentees_can_access(self):
        self.text_question()
        self.client.logout()
        landing = reverse("siwak:landing")
        for method in (self.client.get, self.client.post):
            self.assertRedirects(method(self.url), landing)
        for role in (None, Profile.ROLE_MENTOR):
            user = User.objects.create_user(username=f"non-mentee-{role}", is_staff=True)
            if role:
                Profile.objects.create(user=user, npm="2600000002", role=role)
            self.client.force_login(user)
            self.assertRedirects(self.client.get(self.url), landing)
            self.assertRedirects(self.submit(), landing)
        self.assertFalse(TugasSubmission.objects.exists())

    def test_inactive_task_rejects_submission(self):
        self.tugas.is_active = False
        self.tugas.save()
        self.assertEqual(self.submit().status_code, 404)

    def test_failure_rolls_back_database(self):
        question = self.text_question()
        with self.assertLogs("django.request", level="ERROR"), patch.object(
            Answer, "save", side_effect=RuntimeError("Simulated write failure")
        ):
            with self.assertRaisesMessage(RuntimeError, "Simulated write failure"):
                self.submit(**{f"question_{question.pk}": "Jawaban"})
        self.assertFalse(TugasSubmission.objects.exists())
        self.assertFalse(Answer.objects.exists())

    def test_failed_resubmit_preserves_previous_answers(self):
        question = self.text_question()
        self.submit(**{f"question_{question.pk}": "Lama"})
        old = self.submission()
        with self.assertLogs("django.request", level="ERROR"), patch.object(
            Answer, "save", side_effect=RuntimeError("Write failed")
        ):
            with self.assertRaises(RuntimeError):
                self.submit(**{f"question_{question.pk}": "Baru"})
        self.assertEqual(self.submission().submitted_at, old.submitted_at)
        self.assertEqual(old.answers.get().text_answer, "Lama")

    def test_delete_submission_cleans_answer_files_only_after_commit(self):
        question = self.file_question()
        self.submit(**{f"question_{question.pk}": self.upload("lampiran.png")})
        sub = self.submission()
        file = sub.answers.get().file_answer
        with self.captureOnCommitCallbacks(execute=True):
            sub.delete()
            self.assertTrue(file.storage.exists(file.name))
        self.assertFalse(file.storage.exists(file.name))

    def test_delete_rollback_keeps_files(self):
        question = self.file_question()
        self.submit(**{f"question_{question.pk}": self.upload("lampiran.png")})
        sub = self.submission()
        pk, file = sub.pk, sub.answers.get().file_answer
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    sub.delete()
                    raise RuntimeError("Rollback")
        self.assertEqual(callbacks, [])
        self.assertTrue(TugasSubmission.objects.filter(pk=pk).exists())
        self.assertTrue(file.storage.exists(file.name))

    def test_replaced_answer_file_is_deleted_after_commit(self):
        question = self.file_question()
        self.submit(**{f"question_{question.pk}": self.upload("lampiran.png")})
        answer = self.submission().answers.get()
        old_name = answer.file_answer.name
        with self.captureOnCommitCallbacks(execute=True):
            response = self.submit(**{f"question_{question.pk}": self.upload("baru.png")})
            self.assertEqual(response.status_code, 302)
            self.assertTrue(answer.file_answer.storage.exists(old_name))
        self.assertFalse(answer.file_answer.storage.exists(old_name))

    def test_shared_file_is_not_deleted(self):
        question = self.file_question()
        self.submit(**{f"question_{question.pk}": self.upload("lampiran.png")})
        sub = self.submission()
        shared = sub.answers.get().file_answer
        other = Question.objects.create(tugas=self.tugas, tipe="file", pertanyaan="Lampiran 2")
        answer = Answer.objects.create(submission=sub, question=other, file_answer=shared.name)
        with self.captureOnCommitCallbacks(execute=True):
            answer.delete()
        self.assertTrue(shared.storage.exists(shared.name))

    def test_answer_download_is_scoped_to_owner_responsible_mentor_and_staff(self):
        question = self.file_question()
        self.submit(**{f"question_{question.pk}": self.upload("lampiran.pdf")})
        sub = self.submission()
        url = reverse("siwak:answer_download", args=[sub.pk, sub.answers.get().pk])
        mentor = User.objects.create_user(username="download-mentor")
        profile = Profile.objects.create(
            user=mentor, npm="2600000002", role=Profile.ROLE_MENTOR, kelompok=self.group,
        )
        staff = User.objects.create_user(username="download-staff", is_staff=True)
        for user in (self.user, mentor, staff):
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.7\ncontoh")
        profile.kelompok = None
        profile.save()
        self.client.force_login(mentor)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(User.objects.create_user(username="outsider"))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_answer_without_file_cannot_be_downloaded(self):
        question = self.text_question()
        self.submit(**{f"question_{question.pk}": "Teks"})
        sub = self.submission()
        url = reverse("siwak:answer_download", args=[sub.pk, sub.answers.get().pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def s3_storage(self):
        from storages.backends.s3 import S3Storage
        return S3Storage(
            access_key="testing", secret_key="testing", bucket_name="siwak-test-bucket",
            region_name="ap-southeast-3", endpoint_url="https://s3.ap-southeast-3.amazonaws.com",
            signature_version="s3v4", addressing_style="virtual",
        )

    def s3_answer(self):
        question = self.file_question()
        sub = TugasSubmission.objects.create(tugas=self.tugas, user=self.user)
        return Answer.objects.create(
            submission=sub, question=question, file_answer="siwak/jawaban/test.pdf"
        )

    def test_s3_download_is_signed_only_after_authorization(self):
        storage = self.s3_storage()
        with patch.object(Answer._meta.get_field("file_answer"), "storage", storage):
            answer = self.s3_answer()
            url = reverse("siwak:answer_download", args=[answer.submission_id, answer.pk])
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("X-Amz-Signature=", response.url)
            self.assertIn("X-Amz-Expires=300", response.url)
            self.assertIn("ap-southeast-3", response.url)
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.client.force_login(User.objects.create_user(username="s3-outsider"))
            with patch.object(storage, "url") as sign:
                self.assertEqual(self.client.get(url).status_code, 404)
                sign.assert_not_called()

    def test_s3_delete_object_runs_after_commit(self):
        from botocore.stub import Stubber
        storage = self.s3_storage()
        with patch.object(Answer._meta.get_field("file_answer"), "storage", storage):
            answer = self.s3_answer()
            with Stubber(storage.connection.meta.client) as stub:
                stub.add_response(
                    "delete_object", {}, {"Bucket": "siwak-test-bucket", "Key": answer.file_answer.name}
                )
                with self.captureOnCommitCallbacks(execute=True) as callbacks:
                    answer.delete()
                self.assertEqual(len(callbacks), 1)
                stub.assert_no_pending_responses()

    def test_admin_zip_contains_answer_file_bytes(self):
        from .admin import TugasAdmin
        question = self.file_question()
        self.submit(**{f"question_{question.pk}": self.upload("lampiran.pdf")})
        request = RequestFactory().post("/admin/")
        response = TugasAdmin(Tugas, admin.site).download_all_submissions(
            request, Tugas.objects.filter(pk=self.tugas.pk)
        )
        self.assertEqual(response["Content-Type"], "application/zip")
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual(len(archive.namelist()), 1)
            self.assertEqual(archive.read(archive.namelist()[0]), b"%PDF-1.7\ncontoh")

    def test_admin_panel_links_answer_download(self):
        question = self.file_question()
        self.submit(**{f"question_{question.pk}": self.upload("lampiran.pdf")})
        sub = self.submission()
        self.client.force_login(User.objects.create_user(username="panel-staff", is_staff=True))
        response = self.client.get(reverse("siwak:panel_jawaban", args=[self.tugas.pk]))
        self.assertContains(
            response, reverse("siwak:answer_download", args=[sub.pk, sub.answers.get().pk])
        )

    def test_mentor_pages_show_dynamic_answers(self):
        text, choice, option, file = self.questions()
        self.submit(**{
            f"question_{text.pk}": "Refleksi mentee", f"question_{choice.pk}": option.pk,
            f"question_{file.pk}": self.upload("tambahan.pdf"),
        })
        sub = self.submission()
        mentor = User.objects.create_user(username="review-mentor")
        Profile.objects.create(
            user=mentor, npm="2600000002", role=Profile.ROLE_MENTOR, kelompok=self.group,
        )
        self.client.force_login(mentor)
        attachment_url = reverse("siwak:answer_download", args=[sub.pk, sub.answers.get(question=file).pk])
        for url in (
            reverse("siwak:mentor_mentee_detail", args=[self.profile.pk]),
            reverse("siwak:mentor_task_reviews"),
        ):
            response = self.client.get(url)
            self.assertContains(response, "Refleksi mentee")
            self.assertContains(response, "Setuju")
            self.assertContains(response, attachment_url)
        response = self.client.get(attachment_url)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.7\ncontoh")

    def test_cascade_task_deletion_cleans_all_uploads(self):
        question = self.file_question()
        self.submit(**{f"question_{question.pk}": self.upload("lampiran.pdf")})
        file = self.submission().answers.get().file_answer
        with self.captureOnCommitCallbacks(execute=True):
            Tugas.objects.filter(pk=self.tugas.pk).delete()
        self.assertFalse(file.storage.exists(file.name))

    def test_failure_after_answer_upload_cleans_new_objects(self):
        question = self.file_question()
        uploaded = []
        original_save = Answer.save

        def fail_after_upload(answer, *args, **kwargs):
            original_save(answer, *args, **kwargs)
            if answer.file_answer:
                uploaded.append(answer.file_answer)
                raise RuntimeError("Failure after storage write")

        with self.assertLogs("django.request", level="ERROR"), patch.object(Answer, "save", fail_after_upload):
            with self.assertRaisesMessage(RuntimeError, "Failure after storage write"):
                self.submit(**{f"question_{question.pk}": self.upload("lampiran.pdf")})
        self.assertFalse(TugasSubmission.objects.exists())
        self.assertFalse(Answer.objects.exists())
        self.assertEqual(len(uploaded), 1)
        self.assertFalse(uploaded[0].storage.exists(uploaded[0].name))
