"""Monitoring: konfigurasi privasi Sentry (lihat blok "Monitoring" di
settings.py dan main/monitoring.py).

Event diuji lewat client Sentry sungguhan yang memakai SENTRY_OPTIONS dari
settings, tapi dengan transport penampung: tidak ada yang dikirim ke luar.
"""

from types import SimpleNamespace

import sentry_sdk
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber
from sentry_sdk.transport import Transport

from .monitoring import SentryUserMiddleware, bersihkan_event


class _Penampung(Transport):
    """Transport yang hanya menyimpan event, tidak mengirimnya."""

    def __init__(self):
        super().__init__()
        self.events = []

    def capture_envelope(self, envelope):
        event = envelope.get_event()
        if event:
            self.events.append(event)


class SentryPrivasiTests(SimpleTestCase):
    def _tangkap(self, aksi):
        """Jalankan `aksi` dengan client Sentry berkonfigurasi settings, di
        scope terpisah supaya tidak ada yang tertinggal untuk tes lain."""
        penampung = _Penampung()
        client = sentry_sdk.Client(**{
            **settings.SENTRY_OPTIONS,
            "transport": penampung,
            # Tanpa integrasi: tidak ada yang menambal Django/logging di proses tes.
            "default_integrations": False,
            "auto_enabling_integrations": False,
        })
        with sentry_sdk.isolation_scope() as scope:
            # Seperti scope per request di production: mulai tanpa user.
            scope.set_user(None)
            sentry_sdk.get_current_scope().set_client(client)
            aksi()
        return penampung.events

    def test_sentry_stays_off_in_tests_and_local_debug(self):
        self.assertFalse(settings.SENTRY_AKTIF)
        self.assertFalse(sentry_sdk.get_client().is_active())

    def test_the_privacy_options_are_configured(self):
        opsi = settings.SENTRY_OPTIONS

        self.assertIs(opsi["send_default_pii"], False)
        self.assertEqual(opsi["max_request_body_size"], "never")
        self.assertIs(opsi["include_local_variables"], False)
        self.assertIs(opsi["before_send"], bersihkan_event)
        self.assertIs(opsi["before_send_transaction"], bersihkan_event)
        scrubber = opsi["event_scrubber"]
        self.assertIsInstance(scrubber, EventScrubber)
        self.assertTrue(scrubber.recursive)
        for kunci in [
            *(k.lower() for k in DEFAULT_DENYLIST),
            "notes", "catatan", "feedback", "isi", "jawaban", "npm", "qr", "ticket", "signed",
        ]:
            with self.subTest(kunci=kunci):
                self.assertIn(kunci, scrubber.denylist)

    def test_sensitive_values_never_leave_the_process(self):
        class ProfilPalsu:
            """Seperti Profile: __str__-nya memuat nama dan NPM."""

            def __repr__(self):
                return "Budi Santoso (2506000001)"

        def gagal():
            signed = "RAHASIA-QR"  # noqa: F841 — variabel lokal ini yang diuji
            participant = ProfilPalsu()  # noqa: F841 — tidak tertangkap denylist
            raise ValueError("uji")

        def aksi():
            sentry_sdk.capture_event({
                "message": "uji",
                "request": {
                    "url": "https://fuki.cs.ui.ac.id/siwak/qr/RAHASIA-QR/",
                    "query_string": "ticket=ST-RAHASIA&next=/siwak/",
                },
                "extra": {"npm": "2506000001", "profil": {"notes": "rahasia", "aman": "boleh"}},
            })
            try:
                gagal()
            except ValueError:
                sentry_sdk.capture_exception()

        pesan, galat = self._tangkap(aksi)

        # EventScrubber tidak pernah melihat URL; bersihkan_event yang menutupnya.
        self.assertEqual(pesan["request"]["url"], "https://fuki.cs.ui.ac.id/siwak/qr/[Filtered]/")
        self.assertEqual(pesan["request"]["query_string"], "ticket=[Filtered]&next=/siwak/")
        self.assertEqual(pesan["extra"]["npm"], "[Filtered]")
        self.assertEqual(pesan["extra"]["profil"], {"notes": "[Filtered]", "aman": "boleh"})
        self.assertNotIn("RAHASIA", str(pesan))
        # Variabel lokal tidak dikirim sama sekali: denylist kunci tidak bisa
        # menangkap nama/NPM di dalam __str__ objek seperti `participant` di atas.
        frames = galat["exception"]["values"][0]["stacktrace"]["frames"]
        self.assertTrue(frames)
        self.assertFalse([f for f in frames if "vars" in f])

    def test_the_only_user_context_is_the_user_id(self):
        def lewat_middleware(user):
            request = RequestFactory().get("/")
            request.user = user

            def respons(_request):
                sentry_sdk.capture_message("uji")
                return HttpResponse()

            return lambda: SentryUserMiddleware(respons)(request)

        user = SimpleNamespace(
            is_authenticated=True, pk=42, username="2506000001", email="budi@ui.ac.id"
        )
        (event,) = self._tangkap(lewat_middleware(user))
        self.assertEqual(event["user"], {"id": 42})

        (event,) = self._tangkap(lewat_middleware(AnonymousUser()))
        self.assertNotIn("user", event)

    def test_the_middleware_leaves_sentry_alone_while_it_is_off(self):
        """Without Sentry there is no per-request scope; writing the user
        anyway would park it on the process-wide scope."""
        request = RequestFactory().get("/")
        request.user = SimpleNamespace(is_authenticated=True, pk=7070)

        SentryUserMiddleware(lambda _request: HttpResponse())(request)

        self.assertNotEqual(sentry_sdk.get_isolation_scope()._user, {"id": 7070})
