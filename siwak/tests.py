"""Tests for SIWAK's CAS authentication and student-profile synchronization."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import MabaProfile, PesertaMentoring
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

    def test_creates_profile_and_links_matching_unlinked_participants(self):
        """First login should create a profile and link matching imported data by NPM."""
        matching_participant = PesertaMentoring.objects.create(
            nama_lengkap="Fiqhi Deski Ismail",
            npm="2506534245",
            jurusan="IK",
        )
        other_participant = PesertaMentoring.objects.create(
            nama_lengkap="Mahasiswa Lain",
            npm="2400000000",
            jurusan="SI",
        )

        profile = sync_maba_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        matching_participant.refresh_from_db()
        other_participant.refresh_from_db()
        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.npm, "2506534245")
        self.assertEqual(profile.angkatan, "2025")
        self.assertEqual(matching_participant.user, self.user)
        self.assertIsNone(other_participant.user)

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

    def test_does_not_replace_participant_already_linked_to_another_user(self):
        """Synchronization must not take a participant owned by another user."""
        other_user = User.objects.create_user(username="2400000000")
        participant = PesertaMentoring.objects.create(
            user=other_user,
            nama_lengkap="Fiqhi Deski Ismail",
            npm="2506534245",
            jurusan="IK",
        )

        sync_maba_profile(
            user=self.user,
            npm="2506534245",
            nama_lengkap="Fiqhi Deski Ismail",
            jurusan="IK",
            angkatan="2025",
        )

        participant.refresh_from_db()
        self.assertEqual(participant.user, other_user)


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
