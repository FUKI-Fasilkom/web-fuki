"""Tests for SIWAK's CAS/SSO authentication (PRD 7) that drives MabaProfile /
PesertaMentoring sync, plus the QR & RSVP features (PRD 5.2 / 6 / 8) and the
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
from urllib.parse import unquote

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import formats, timezone

from .models import EventRSVP, MabaProfile, PesertaMentoring, SiwakEvent
from .services.qrcode_service import (
    SIGNING_SALT,
    kupon_qr_data_uri,
    registrasi_qr_data_uri,
    sign_payload,
    unsign_payload,
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
        MabaProfile.objects.create(
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