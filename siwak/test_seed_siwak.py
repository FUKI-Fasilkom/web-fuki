"""Tests for the CSV part of `seed_siwak` and the login sync of seeded mentees."""

import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from .models import KelompokMentoring, Profile, SiwakEvent, SiwakInfo, Tugas
from .sso import handle_cas_login

User = get_user_model()

HEADER = "Kelompok,Nama,NPM,Group Whatsapp\r\n"
LINK_A = "https://chat.whatsapp.com/AAAA?s=cl&p=i&mlu=4&ilr=4"
LINK_B = "https://chat.whatsapp.com/BBBB?s=cl&p=i&mlu=4&ilr=4"


class SeedPengelompokanTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        # Berkas bawaan dicari di BASE_DIR; arahkan ke folder kosong supaya CSV
        # asli di root proyek tidak ikut ter-seed.
        self.enterContext(override_settings(BASE_DIR=self.dir))

    def tulis(self, nama, isi, bom=False):
        path = self.dir / nama
        path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + (HEADER + isi).encode())
        return str(path)

    def seed(self, *csv_paths):
        out = StringIO()
        args = [a for p in csv_paths for a in ("--csv", p)]
        call_command("seed_siwak", *args, stdout=out)
        return out.getvalue()

    def test_seeds_kelompok_with_whatsapp_link_and_mentees(self):
        path = self.tulis(
            "ikhwan.csv",
            f"I-1,Fulan Satu,2606000001,{LINK_A}\r\n"
            f"I-1,Fulan Dua,2606000002,{LINK_A}\r\n"
            f"I-2,Fulan Tiga,2606000003,{LINK_B}\r\n",
        )

        self.seed(path)

        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="I-1").link_grup, LINK_A)
        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="I-2").link_grup, LINK_B)
        profil = Profile.objects.get(npm="2606000001")
        self.assertEqual(profil.nama_lengkap, "Fulan Satu")
        self.assertEqual(profil.role, Profile.ROLE_MENTEE)
        self.assertEqual(profil.kelompok.nama_kelompok, "I-1")
        self.assertEqual(profil.angkatan, "2026")
        self.assertEqual(profil.jurusan, "")
        self.assertIsNone(profil.user)
        self.assertEqual(Profile.objects.filter(kelompok__nama_kelompok="I-1", role="mentee").count(), 2)

    def test_kapasitas_is_the_number_of_mentees_listed_in_the_csv(self):
        path = self.tulis(
            "i.csv",
            f"I-1,Satu,2606000001,{LINK_A}\r\n"
            f"I-1,Dua,2606000002,{LINK_A}\r\n"
            f"I-1,Tiga,2606000003,{LINK_A}\r\n"
            f"I-2,Empat,2606000004,{LINK_B}\r\n",
        )

        self.seed(path)

        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="I-1").kapasitas, 3)
        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="I-2").kapasitas, 1)

    def test_kapasitas_counts_rows_that_could_not_be_seeded(self):
        """No-NPM rows and rows placed elsewhere still belong to the group on paper."""
        path = self.tulis(
            "i.csv",
            f"I-1,Ada NPM,2606000001,{LINK_A}\r\n"
            f"I-1,Tanpa NPM,,{LINK_A}\r\n"
            f"I-2,Ada NPM,2606000001,{LINK_B}\r\n"
            f"I-2,Lain,2606000002,{LINK_B}\r\n",
        )

        self.seed(path)

        # I-1: Ada NPM + Tanpa NPM; I-2: the duplicate of Ada NPM + Lain.
        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="I-1").kapasitas, 2)
        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="I-2").kapasitas, 2)
        self.assertEqual(Profile.objects.filter(kelompok__nama_kelompok="I-2", role="mentee").count(), 1)

    def test_same_npm_repeated_in_one_kelompok_counts_once(self):
        path = self.tulis(
            "i.csv",
            f"I-1,Fulan,2606000001,{LINK_A}\r\n"
            f"I-1,Fulan,2606000001,{LINK_A}\r\n",
        )

        self.seed(path)

        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="I-1").kapasitas, 1)

    def test_rerun_updates_kapasitas_of_an_existing_kelompok(self):
        KelompokMentoring.objects.create(nama_kelompok="I-1", link_grup=LINK_A, kapasitas=15)

        self.seed(self.tulis("i.csv", f"I-1,Satu,2606000001,{LINK_A}\r\nI-1,Dua,2606000002,{LINK_A}\r\n"))

        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="I-1").kapasitas, 2)

    def test_kelompok_only_in_the_mentor_csv_keeps_the_default_kapasitas(self):
        mentor = self.dir / "m.csv"
        mentor.write_bytes(b"Kelompok,Mentor\r\nI-9,Rafa\r\n")

        call_command("seed_siwak", "--mentor-csv", str(mentor), stdout=StringIO())

        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="I-9").kapasitas, 15)

    def test_reads_files_with_bom_and_collapses_name_whitespace(self):
        path = self.tulis("a.csv", f"A-1,  Siti   Aisyah ,2606000010,{LINK_A}\r\n", bom=True)

        self.seed(path)

        self.assertEqual(Profile.objects.get(npm="2606000010").nama_lengkap, "Siti Aisyah")

    def test_rows_without_a_name_are_ignored(self):
        """Akhwat.csv ends with a pasted list of links: no Nama, no NPM."""
        path = self.tulis(
            "a.csv",
            f"A-1,Siti,2606000010,{LINK_A}\r\n"
            "A-1,,,Group Whatsapp\r\n"
            f"A-1,,,{LINK_B}\r\n",
        )

        out = self.seed(path)

        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="A-1").link_grup, LINK_A)
        self.assertEqual(Profile.objects.filter(role=Profile.ROLE_MENTEE, kelompok__nama_kelompok="A-1").count(), 1)
        self.assertIn("2 baris tanpa nama diabaikan", out)

    def test_row_without_npm_is_skipped_and_reported(self):
        path = self.tulis(
            "i.csv",
            f"I-1,Ada NPM,2606000001,{LINK_A}\r\n"
            f"I-1,Tanpa NPM,,{LINK_A}\r\n",
        )

        out = self.seed(path)

        self.assertFalse(Profile.objects.filter(nama_lengkap="Tanpa NPM").exists())
        self.assertIn("Tanpa NPM", out)
        self.assertIn("tanpa NPM, dilewati", out)

    def test_duplicate_npm_keeps_first_placement_and_reports_it(self):
        path = self.tulis(
            "i.csv",
            f"I-1,Fulan,2606000001,{LINK_A}\r\n"
            f"I-2,Fulan,2606000001,{LINK_B}\r\n",
        )

        out = self.seed(path)

        self.assertEqual(Profile.objects.get(npm="2606000001").kelompok.nama_kelompok, "I-1")
        self.assertIn("sudah masuk I-1", out)

    def test_same_npm_repeated_in_same_kelompok_is_silent(self):
        path = self.tulis(
            "i.csv",
            f"I-1,Fulan,2606000001,{LINK_A}\r\n"
            f"I-1,Fulan,2606000001,{LINK_A}\r\n",
        )

        out = self.seed(path)

        self.assertEqual(Profile.objects.filter(npm="2606000001").count(), 1)
        self.assertNotIn("sudah masuk", out)

    def test_link_shared_by_several_kelompok_is_reported_but_seeded(self):
        path = self.tulis(
            "a.csv",
            f"A-1,Satu,2606000001,{LINK_A}\r\n"
            f"A-2,Dua,2606000002,{LINK_A}\r\n",
        )

        out = self.seed(path)

        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="A-2").link_grup, LINK_A)
        self.assertIn("dipakai bersama oleh 2 kelompok", out)

    def test_rerun_is_idempotent(self):
        path = self.tulis("i.csv", f"I-1,Fulan,2606000001,{LINK_A}\r\nI-2,Dua,2606000002,{LINK_B}\r\n")

        self.seed(path)
        kelompok, profil = KelompokMentoring.objects.count(), Profile.objects.count()
        self.seed(path)

        self.assertEqual(KelompokMentoring.objects.count(), kelompok)
        self.assertEqual(Profile.objects.count(), profil)

    def test_rerun_applies_a_corrected_link(self):
        self.seed(self.tulis("i.csv", f"I-1,Fulan,2606000001,{LINK_A}\r\n"))
        self.seed(self.tulis("i.csv", f"I-1,Fulan,2606000001,{LINK_B}\r\n"))

        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="I-1").link_grup, LINK_B)

    def test_existing_mentor_is_never_turned_into_a_mentee(self):
        mentor = Profile.objects.create(npm="2606000001", nama_lengkap="Kak Mentor", role=Profile.ROLE_MENTOR)

        out = self.seed(self.tulis("i.csv", f"I-1,Fulan,2606000001,{LINK_A}\r\n"))

        mentor.refresh_from_db()
        self.assertEqual(mentor.role, Profile.ROLE_MENTOR)
        self.assertIsNone(mentor.kelompok)
        self.assertIn("sudah terdaftar sebagai mentor", out)

    def test_existing_profile_keeps_its_name_and_jurusan(self):
        Profile.objects.create(npm="2606000001", nama_lengkap="Nama Dari SSO", jurusan="SI")

        self.seed(self.tulis("i.csv", f"I-1,Nama Di CSV,2606000001,{LINK_A}\r\n"))

        profil = Profile.objects.get(npm="2606000001")
        self.assertEqual(profil.nama_lengkap, "Nama Dari SSO")
        self.assertEqual(profil.jurusan, "SI")
        self.assertEqual(profil.role, Profile.ROLE_MENTEE)
        self.assertEqual(profil.kelompok.nama_kelompok, "I-1")

    def test_missing_explicit_csv_fails_before_writing_anything(self):
        with self.assertRaisesRegex(CommandError, "tidak ditemukan"):
            call_command("seed_siwak", "--csv", str(self.dir / "tidak-ada.csv"), stdout=StringIO())

        self.assertFalse(KelompokMentoring.objects.exists())

    def test_wrong_header_fails_before_writing_anything(self):
        path = self.dir / "salah.csv"
        path.write_text("Nama,NPM\r\nFulan,2606000001\r\n")

        with self.assertRaisesRegex(CommandError, "kolom .*tidak ada"):
            call_command("seed_siwak", "--csv", str(path), stdout=StringIO())

        self.assertFalse(KelompokMentoring.objects.exists())

    def test_default_csvs_are_optional(self):
        """The CSVs hold student data and are not committed; a clean checkout still seeds."""
        with override_settings(BASE_DIR=self.dir):
            out = StringIO()
            call_command("seed_siwak", stdout=out)

        self.assertIn("tidak ditemukan, dilewati", out.getvalue())
        self.assertTrue(Profile.objects.filter(npm="2506000001").exists())

    def test_default_csvs_are_read_from_project_root(self):
        self.tulis("SIWAK_2026_Pengelompokan_Mentoring_Group_Ikhwan.csv", f"I-1,Fulan,2606000001,{LINK_A}\r\n")
        self.tulis("SIWAK_2026_Pengelompokan_Mentoring_Group_Akhwat.csv", f"A-1,Siti,2606000002,{LINK_B}\r\n")

        with override_settings(BASE_DIR=self.dir):
            call_command("seed_siwak", stdout=StringIO())

        self.assertEqual(Profile.objects.get(npm="2606000001").kelompok.nama_kelompok, "I-1")
        self.assertEqual(Profile.objects.get(npm="2606000002").kelompok.nama_kelompok, "A-1")


class SeedMentorTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.enterContext(override_settings(BASE_DIR=self.dir))

    def tulis(self, nama, isi):
        path = self.dir / nama
        path.write_bytes(("Kelompok,Mentor\r\n" + isi).encode())
        return str(path)

    def seed(self, *mentor_csv, mentee_csv=None):
        out = StringIO()
        args = [a for p in mentor_csv for a in ("--mentor-csv", p)]
        if mentee_csv:
            args += ["--csv", mentee_csv]
        call_command("seed_siwak", *args, stdout=out)
        return out.getvalue()

    def mentee_csv(self, isi):
        path = self.dir / "mentee.csv"
        path.write_bytes((HEADER + isi).encode())
        return str(path)

    def test_mentor_is_placed_in_existing_kelompok_without_npm_or_user(self):
        mentee = self.mentee_csv(f"I-1,Fulan,2606000001,{LINK_A}\r\n")

        self.seed(self.tulis("m.csv", "I-1,Joko Pebrianto\r\n"), mentee_csv=mentee)

        mentor = Profile.objects.get(nama_lengkap="Joko Pebrianto")
        self.assertEqual(mentor.role, Profile.ROLE_MENTOR)
        self.assertEqual(mentor.kelompok.nama_kelompok, "I-1")
        self.assertEqual(mentor.kelompok.link_grup, LINK_A)
        self.assertIsNone(mentor.npm)
        self.assertIsNone(mentor.user)
        self.assertEqual(mentor.auth_source, Profile.SOURCE_SSO)
        self.assertEqual(KelompokMentoring.objects.filter(nama_kelompok="I-1").count(), 1)

    def test_two_mentors_in_one_cell_are_split(self):
        self.seed(self.tulis("m.csv", "I-5,Khawarizmi Aydin & Salman\r\n"))

        kelompok = KelompokMentoring.objects.get(nama_kelompok="I-5")
        self.assertEqual(
            sorted(kelompok.daftar_mentor.values_list("nama_lengkap", flat=True)),
            ["Khawarizmi Aydin", "Salman"],
        )

    def test_kelompok_only_in_mentor_csv_is_created_and_reported(self):
        out = self.seed(self.tulis("m.csv", "I-9,Rafa\r\n"))

        self.assertEqual(KelompokMentoring.objects.get(nama_kelompok="I-9").link_grup, "")
        self.assertIn("Kelompok I-9 hanya ada di CSV mentor", out)

    def test_rerun_is_idempotent(self):
        path = self.tulis("m.csv", "I-1,Joko\r\nI-2,Nur & Fajar\r\n")

        self.seed(path)
        jumlah = Profile.objects.filter(role=Profile.ROLE_MENTOR).count()
        self.seed(path)

        self.assertEqual(Profile.objects.filter(role=Profile.ROLE_MENTOR).count(), jumlah)

    def test_existing_mentor_with_same_name_is_reused_not_duplicated(self):
        """A mentor staff already registered (with NPM) keeps their NPM and account."""
        kelompok = KelompokMentoring.objects.create(nama_kelompok="I-1")
        ada = Profile.objects.create(
            npm="2106000001", nama_lengkap="Joko Pebrianto", role=Profile.ROLE_MENTOR
        )

        self.seed(self.tulis("m.csv", "I-1,joko pebrianto\r\n"))

        self.assertEqual(Profile.objects.filter(nama_lengkap__iexact="Joko Pebrianto").count(), 1)
        ada.refresh_from_db()
        self.assertEqual(ada.npm, "2106000001")
        self.assertEqual(ada.kelompok, kelompok)

    def test_existing_mentor_keeps_the_kelompok_staff_gave_them(self):
        milik = KelompokMentoring.objects.create(nama_kelompok="I-7")
        ada = Profile.objects.create(
            npm="2106000001", nama_lengkap="Joko", role=Profile.ROLE_MENTOR, kelompok=milik
        )

        out = self.seed(self.tulis("m.csv", "I-1,Joko\r\n"))

        ada.refresh_from_db()
        self.assertEqual(ada.kelompok, milik)
        self.assertIn("sudah memegang I-7, dibiarkan", out)

    def test_same_name_listed_twice_keeps_first_kelompok(self):
        out = self.seed(self.tulis("m.csv", "I-1,Joko\r\nI-2,Joko\r\n"))

        self.assertEqual(Profile.objects.filter(nama_lengkap="Joko").count(), 1)
        self.assertEqual(Profile.objects.get(nama_lengkap="Joko").kelompok.nama_kelompok, "I-1")
        self.assertIn("sudah memegang I-1", out)

    def test_row_without_mentor_is_ignored(self):
        out = self.seed(self.tulis("m.csv", "I-1,\r\nI-2,Nur\r\n"))

        self.assertEqual(Profile.objects.filter(role=Profile.ROLE_MENTOR, kelompok__nama_kelompok="I-1").count(), 0)
        self.assertIn("1 baris tanpa mentor diabaikan", out)

    def test_wrong_header_fails_before_writing_anything(self):
        path = self.dir / "salah.csv"
        path.write_text("Kelompok,Nama\r\nI-1,Joko\r\n")

        with self.assertRaisesRegex(CommandError, "kolom Mentor tidak ada"):
            call_command("seed_siwak", "--mentor-csv", str(path), stdout=StringIO())

        self.assertFalse(KelompokMentoring.objects.exists())

    def test_default_mentor_csvs_are_read_from_project_root(self):
        self.tulis("Kelompok_Mentor_Ikhwan.csv", "I-1,Joko\r\n")
        self.tulis("Kelompok_Mentor_Akhwat.csv", "A-1,Fitria\r\n")

        call_command("seed_siwak", stdout=StringIO())

        self.assertEqual(Profile.objects.get(nama_lengkap="Joko").kelompok.nama_kelompok, "I-1")
        self.assertEqual(Profile.objects.get(nama_lengkap="Fitria").kelompok.nama_kelompok, "A-1")

    def test_prepared_mentor_is_claimed_once_staff_add_the_npm(self):
        """The whole point of seeding without NPM: staff add it, SSO login claims the row."""
        self.seed(self.tulis("m.csv", "I-1,Joko Pebrianto\r\n"))
        mentor = Profile.objects.get(nama_lengkap="Joko Pebrianto")
        mentor.npm = "2106000001"
        mentor.save()
        user = User.objects.create_user(username="joko.pebrianto")

        handle_cas_login(
            sender=self.__class__,
            user=user,
            username="joko.pebrianto",
            attributes={"npm": ["2106000001"], "nama": ["Joko Pebrianto"], "kd_org": ["01.00.12.01"]},
        )

        mentor.refresh_from_db()
        self.assertEqual(mentor.user, user)
        self.assertEqual(mentor.role, Profile.ROLE_MENTOR)
        self.assertEqual(mentor.kelompok.nama_kelompok, "I-1")
        self.assertEqual(mentor.jurusan, "IK")


class SeedCsvOnlyTests(TestCase):
    """`--csv-only` is what runs on the server: it must not touch the demo content."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.enterContext(override_settings(BASE_DIR=self.dir))

    def test_seeds_csv_data_but_no_demo_content(self):
        (self.dir / "SIWAK_2026_Pengelompokan_Mentoring_Group_Ikhwan.csv").write_bytes(
            (HEADER + f"I-1,Fulan,2606000001,{LINK_A}\r\n").encode()
        )
        (self.dir / "Kelompok_Mentor_Ikhwan.csv").write_bytes(b"Kelompok,Mentor\r\nI-1,Joko\r\n")

        out = StringIO()
        call_command("seed_siwak", "--csv-only", stdout=out)

        self.assertEqual(Profile.objects.get(npm="2606000001").kelompok.nama_kelompok, "I-1")
        self.assertEqual(Profile.objects.get(nama_lengkap="Joko").kelompok.nama_kelompok, "I-1")
        # Nothing from the demo block: no demo kelompok/mentors/mentee, no events, no info.
        self.assertEqual(list(KelompokMentoring.objects.values_list("nama_kelompok", flat=True)), ["I-1"])
        self.assertFalse(Profile.objects.filter(npm__in=["2506000001", "2206000001"]).exists())
        self.assertFalse(SiwakEvent.objects.exists())
        self.assertFalse(SiwakInfo.objects.exists())
        self.assertFalse(Tugas.objects.exists())
        self.assertIn("Data pengelompokan SIWAK berhasil diisi", out.getvalue())

    def test_does_not_overwrite_real_content(self):
        info = SiwakInfo.get_solo()
        info.kontak_cp = "https://wa.me/628111111111"
        info.save()
        SiwakEvent.objects.create(judul="Pre-Event SIWAK", tanggal="2026-09-01", lokasi="Lokasi Asli", urutan=1)
        (self.dir / "Kelompok_Mentor_Ikhwan.csv").write_bytes(b"Kelompok,Mentor\r\nI-1,Joko\r\n")

        call_command("seed_siwak", "--csv-only", stdout=StringIO())

        self.assertEqual(SiwakInfo.get_solo().kontak_cp, "https://wa.me/628111111111")
        self.assertEqual(SiwakEvent.objects.get(judul="Pre-Event SIWAK").lokasi, "Lokasi Asli")

    def test_fails_loudly_when_no_csv_is_found(self):
        with self.assertRaisesRegex(CommandError, "Tidak ada CSV yang terbaca"):
            call_command("seed_siwak", "--csv-only", stdout=StringIO())

        self.assertFalse(KelompokMentoring.objects.exists())

    def test_failure_rolls_back_everything(self):
        """A bad mentor CSV must not leave the mentees half-seeded."""
        (self.dir / "SIWAK_2026_Pengelompokan_Mentoring_Group_Ikhwan.csv").write_bytes(
            (HEADER + f"I-1,Fulan,2606000001,{LINK_A}\r\n").encode()
        )
        (self.dir / "Kelompok_Mentor_Ikhwan.csv").write_bytes(b"Kelompok,Nama\r\nI-1,Joko\r\n")

        with self.assertRaises(CommandError):
            call_command("seed_siwak", "--csv-only", stdout=StringIO())

        self.assertFalse(Profile.objects.exists())


class SeededMenteeLoginSyncTests(TestCase):
    """A seeded mentee has no jurusan; their first SSO login must fill it in."""

    def test_login_fills_jurusan_and_keeps_role_and_kelompok(self):
        kelompok = KelompokMentoring.objects.create(nama_kelompok="I-1")
        seeded = Profile.objects.create(
            npm="2606000001", nama_lengkap="Fulan (CSV)", angkatan="2026",
            role=Profile.ROLE_MENTEE, kelompok=kelompok,
        )
        self.assertEqual(seeded.jurusan, "")
        user = User.objects.create_user(username="fulan.satu")

        handle_cas_login(
            sender=self.__class__,
            user=user,
            username="fulan.satu",
            attributes={"npm": ["2606000001"], "nama": ["Fulan Satu"], "kd_org": ["06.00.12.01"]},
        )

        seeded.refresh_from_db()
        self.assertEqual(Profile.objects.count(), 1)
        self.assertEqual(seeded.user, user)
        self.assertEqual(seeded.jurusan, "SI")
        self.assertEqual(seeded.nama_lengkap, "Fulan Satu")
        self.assertEqual(seeded.role, Profile.ROLE_MENTEE)
        self.assertEqual(seeded.kelompok, kelompok)

    def test_every_login_refreshes_jurusan(self):
        """Not only the first login: the value follows SSO, so a stale or blank one heals."""
        user = User.objects.create_user(username="fulan.dua")
        profil = Profile.objects.create(
            user=user, npm="2606000002", nama_lengkap="Fulan Dua", jurusan="",
            role=Profile.ROLE_MENTEE,
        )

        handle_cas_login(
            sender=self.__class__,
            user=user,
            username="fulan.dua",
            attributes={"npm": ["2606000002"], "nama": ["Fulan Dua"], "kd_org": ["01.00.12.01"]},
        )

        profil.refresh_from_db()
        self.assertEqual(profil.jurusan, "IK")
