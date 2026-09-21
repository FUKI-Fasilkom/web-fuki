"""Tests for `seed_rsvp`: RSVP dari form lain harus sama dengan RSVP lewat web."""

import re
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from .management.commands.seed_rsvp import bandingkan_nama, kehadiran_dari_form
from .models import EventRSVP, Profile, SiwakEvent
from .services.qrcode_service import sign_payload, unsign_payload
from .views import _find_rsvp

User = get_user_model()

HEADER = (
    'Timestamp,Nama Lengkap,NPM,Ikhwan atau akhwat?,Apakah kamu bisa hadir?,'
    '"Apa alasan kamu tak bisa hadir? \n(Ketik "" - "" kalau bisa hadir)"\r\n'
)


class SeedRSVPTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.event = SiwakEvent.objects.create(judul="Mentoring #1", rsvp_dibuka=False)

    def mentee(self, npm, nama, login=True):
        user = User.objects.create_user(username=f"u{npm}") if login else None
        return Profile.objects.create(
            user=user, npm=npm, nama_lengkap=nama, role=Profile.ROLE_MENTEE
        )

    def seed(self, isi, *args):
        path = self.dir / "rsvp.csv"
        path.write_bytes(b"\xef\xbb\xbf" + (HEADER + isi).encode())
        out = StringIO()
        call_command("seed_rsvp", "--csv", str(path), *args, stdout=out)
        return out.getvalue()

    # -- pemetaan jawaban ---------------------------------------------------

    def test_ya_menjadi_hadir_tanpa_alasan(self):
        self.mentee("2606000001", "Fulan Satu")
        self.seed("16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n")

        rsvp = EventRSVP.objects.get()
        self.assertEqual((rsvp.kehadiran, rsvp.alasan_izin), ("hadir", ""))

    def test_tidak_dengan_alasan_menjadi_izin(self):
        self.mentee("2606000001", "Fulan Satu")
        self.seed("16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Tidak,ada acara keluarga \r\n")

        rsvp = EventRSVP.objects.get()
        self.assertEqual((rsvp.kehadiran, rsvp.alasan_izin), ("izin", "ada acara keluarga"))

    def test_tidak_tanpa_alasan_menjadi_tidak_hadir(self):
        self.assertEqual(kehadiran_dari_form("tidak", "-"), ("tidak_hadir", ""))
        self.assertEqual(kehadiran_dari_form("tidak", '"-"'), ("tidak_hadir", ""))
        self.assertEqual(kehadiran_dari_form("tidak", ""), ("tidak_hadir", ""))

    def test_alasan_terlalu_panjang_dipotong_dan_dilaporkan(self):
        self.mentee("2606000001", "Fulan Satu")
        out = self.seed(f"16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Tidak,{'x' * 400}\r\n")

        self.assertEqual(len(EventRSVP.objects.get().alasan_izin), 300)
        self.assertIn("dipotong", out)

    def test_hadir_dengan_keterangan_dilaporkan_tapi_tidak_disimpan(self):
        self.mentee("2606000001", "Fulan Satu")
        out = self.seed("16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,agak terlambat\r\n")

        self.assertEqual(EventRSVP.objects.get().alasan_izin, "")
        self.assertIn("agak terlambat", out)

    # -- identik dengan RSVP lewat web -------------------------------------

    def test_seeded_rsvp_matches_one_created_through_the_web_form(self):
        seeded = self.mentee("2606000001", "Fulan Satu")
        web = self.mentee("2606000002", "Fulan Dua")
        self.event.rsvp_dibuka = True
        self.event.save()
        self.client.force_login(web.user)
        self.client.post(
            reverse("siwak:rsvp", args=[self.event.id]), {"kehadiran": "hadir", "npm": "2606000002"}
        )
        self.seed("16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n")

        a = EventRSVP.objects.get(user=seeded.user)
        b = EventRSVP.objects.get(user=web.user)
        for field in ("kehadiran", "alasan_izin", "status_kehadiran", "status_kupon",
                      "checked_in_at", "redeemed_at"):
            self.assertEqual(getattr(a, field), getattr(b, field), field)
        # Token sama bentuknya (uuid4 hex dari _new_token) dan unik per RSVP.
        for field in ("qr_registrasi_token", "qr_kupon_token"):
            self.assertRegex(getattr(a, field), r"^[0-9a-f]{32}$")
            self.assertNotEqual(getattr(a, field), getattr(b, field))
        self.assertNotEqual(a.qr_registrasi_token, a.qr_kupon_token)

    def test_rsvp_page_shows_qr_and_signed_payloads_resolve_to_the_seeded_rsvp(self):
        profil = self.mentee("2606000001", "Fulan Satu")
        self.seed("16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n")
        rsvp = EventRSVP.objects.get()

        # Event ditutup, tapi RSVP yang sudah ada tetap menampilkan QR-nya.
        self.client.force_login(profil.user)
        response = self.client.get(reverse("siwak:rsvp", args=[self.event.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "QR Kehadiran")
        self.assertContains(response, "QR Kupon Makan")
        self.assertEqual(len(re.findall(r"data:image/png;base64,", response.content.decode())), 2)

        # Payload yang ditandatangani dengan salt siwak.qr kembali ke RSVP ini.
        for kind, token in (
            ("registrasi", rsvp.qr_registrasi_token), ("kupon", rsvp.qr_kupon_token)
        ):
            payload = unsign_payload(sign_payload(kind, token))
            self.assertEqual(_find_rsvp(payload["kind"], payload["token"]), rsvp)

    def test_created_at_is_the_form_timestamp_in_local_time(self):
        self.mentee("2606000001", "Fulan Satu")
        self.seed("16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n")

        from django.utils import timezone
        waktu = timezone.localtime(EventRSVP.objects.get().created_at)
        self.assertEqual(waktu.strftime("%d/%m/%Y %H:%M:%S"), "16/09/2026 20:27:30")

    # -- pencocokan Profile ------------------------------------------------

    def test_npm_without_profile_is_reported_and_skipped(self):
        out = self.seed("16/09/2026 20:27:30,Orang Asing,2606999999,Ikhwan,Ya,-\r\n")

        self.assertEqual(EventRSVP.objects.count(), 0)
        self.assertIn("tidak ada Profile dengan NPM ini", out)
        self.assertIn("tanpa Profile: 1", out)

    def test_profile_without_login_account_is_reported_and_skipped(self):
        self.mentee("2606000001", "Fulan Satu", login=False)
        out = self.seed("16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n")

        self.assertEqual(EventRSVP.objects.count(), 0)
        self.assertIn("belum punya akun login", out)
        self.assertIn("belum punya akun login: 1", out)

    def test_rerun_after_login_seeds_the_remaining_ones(self):
        profil = self.mentee("2606000001", "Fulan Satu", login=False)
        isi = "16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n"
        self.seed(isi)
        profil.user = User.objects.create_user(username="fulan.satu")
        profil.save()

        self.seed(isi)

        self.assertEqual(EventRSVP.objects.get().user, profil.user)

    def test_name_check_ignores_case_spacing_and_punctuation(self):
        self.assertEqual(bandingkan_nama("M.Januar Adam", "M. Januar Adam"), "sama")
        self.assertEqual(bandingkan_nama("Mirza Neo Pramudya", "mirza  neo pramudya "), "sama")
        self.assertEqual(
            bandingkan_nama("Muhammad Rafi Farras Arizanov", "Muhammad Rafi Farras A"), "mirip"
        )
        self.assertEqual(
            bandingkan_nama("Muhammad Daffa Fahrizal Despriyambod",
                            "Muhammad Daffa Fahrizal Despriyambodo"), "mirip"
        )
        self.assertEqual(bandingkan_nama("Fulan Satu", "Budi Santoso"), "beda")

    def test_slightly_different_name_is_seeded_with_a_note(self):
        self.mentee("2606000001", "Muhammad Rafi Farras Arizanov")
        out = self.seed("16/09/2026 20:27:30,Muhammad Rafi Farras A,2606000001,Ikhwan,Ya,-\r\n")

        self.assertEqual(EventRSVP.objects.count(), 1)
        self.assertIn("sedikit beda", out)

    def test_very_different_name_is_skipped_unless_accepted(self):
        self.mentee("2606000001", "Fulan Satu")
        isi = "16/09/2026 20:27:30,Budi Santoso,2606000001,Ikhwan,Ya,-\r\n"

        out = self.seed(isi)
        self.assertEqual(EventRSVP.objects.count(), 0)
        self.assertIn("sangat berbeda", out)
        self.assertIn("nama beda: 1", out)

        self.seed(isi, "--terima-beda-nama")
        self.assertEqual(EventRSVP.objects.count(), 1)

    def test_profile_name_is_never_modified(self):
        profil = self.mentee("2606000001", "Muhammad Rafi Farras Arizanov")
        self.seed("16/09/2026 20:27:30,Muhammad Rafi Farras A,2606000001,Ikhwan,Ya,-\r\n")

        profil.refresh_from_db()
        self.assertEqual(profil.nama_lengkap, "Muhammad Rafi Farras Arizanov")

    # -- duplikat & idempotensi ---------------------------------------------

    def test_latest_submission_wins_regardless_of_row_order(self):
        self.mentee("2606000001", "Fulan Satu")
        out = self.seed(
            "20/09/2026 10:00:00,Fulan Satu,2606000001,Ikhwan,Tidak,ada acara\r\n"
            "16/09/2026 10:00:00,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n"
        )

        rsvp = EventRSVP.objects.get()
        self.assertEqual((rsvp.kehadiran, rsvp.alasan_izin), ("izin", "ada acara"))
        self.assertIn("jawaban terbaru dipakai", out)

    def test_identical_resubmissions_collapse_quietly(self):
        self.mentee("2606000001", "Fulan Satu")
        out = self.seed(
            "16/09/2026 10:00:00,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n"
            "18/09/2026 10:00:00,Fulan Satu ,2606000001,Ikhwan,Ya,-\r\n"
        )

        self.assertEqual(EventRSVP.objects.count(), 1)
        self.assertNotIn("jawaban terbaru dipakai", out)

    def test_rerun_keeps_existing_rsvp_and_tokens(self):
        self.mentee("2606000001", "Fulan Satu")
        isi = "16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n"
        self.seed(isi)
        rsvp = EventRSVP.objects.get()
        EventRSVP.objects.filter(pk=rsvp.pk).update(status_kehadiran="hadir")

        out = self.seed(isi)

        again = EventRSVP.objects.get()
        self.assertEqual(again.qr_registrasi_token, rsvp.qr_registrasi_token)
        self.assertEqual(again.qr_kupon_token, rsvp.qr_kupon_token)
        self.assertEqual(again.status_kehadiran, "hadir")
        self.assertIn("Sudah punya RSVP: 1", out)

    def test_rsvp_made_on_the_web_is_not_overwritten(self):
        profil = self.mentee("2606000001", "Fulan Satu")
        EventRSVP.objects.create(event=self.event, user=profil.user, kehadiran="izin", alasan_izin="x")

        self.seed("16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n")

        self.assertEqual(EventRSVP.objects.get().kehadiran, "izin")

    def test_dry_run_writes_nothing(self):
        self.mentee("2606000001", "Fulan Satu")
        out = self.seed("16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n", "--dry-run")

        self.assertEqual(EventRSVP.objects.count(), 0)
        self.assertIn("RSVP dibuat: 1", out)
        self.assertIn("DRY RUN", out)

    # -- masukan bermasalah -------------------------------------------------

    def test_invalid_rows_are_reported_and_valid_rows_still_seeded(self):
        self.mentee("2606000001", "Fulan Satu")
        out = self.seed(
            "16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n"
            "16/09/2026 20:27:30,Tanpa Npm,,Ikhwan,Ya,-\r\n"
            "16/09/2026 20:27:30,Jawaban Aneh,2606000002,Ikhwan,Mungkin,-\r\n"
            "kemarin,Waktu Aneh,2606000003,Ikhwan,Ya,-\r\n"
        )

        self.assertEqual(EventRSVP.objects.count(), 1)
        self.assertIn("NPM tidak valid", out)
        self.assertIn("tidak dikenali", out)
        self.assertIn("timestamp tidak valid", out)

    def test_missing_csv_fails_loudly(self):
        with self.assertRaisesMessage(CommandError, "CSV tidak ditemukan"):
            call_command("seed_rsvp", "--csv", str(self.dir / "tidak-ada.csv"), stdout=StringIO())

    def test_csv_without_required_column_fails_loudly(self):
        path = self.dir / "rusak.csv"
        path.write_text("Nama,NPM\r\nx,1\r\n", encoding="utf-8")
        with self.assertRaisesMessage(CommandError, "kolom"):
            call_command("seed_rsvp", "--csv", str(path), stdout=StringIO())

    def test_several_events_require_an_explicit_choice(self):
        SiwakEvent.objects.create(judul="Main Event")
        self.mentee("2606000001", "Fulan Satu")
        with self.assertRaisesMessage(CommandError, "--event"):
            self.seed("16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n")

        self.seed(
            "16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n", "--event", str(self.event.pk)
        )
        self.assertEqual(EventRSVP.objects.get().event, self.event)

    def test_unknown_event_id_fails(self):
        with self.assertRaisesMessage(CommandError, "tidak ada"):
            self.seed("16/09/2026 20:27:30,Fulan Satu,2606000001,Ikhwan,Ya,-\r\n", "--event", "999")
