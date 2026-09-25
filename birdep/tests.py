import csv
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from birdep.management.commands.seed_fungsionaris_foto import CSV_DEFAULT, baca_csv
from birdep.models import BirDep, Fungsionaris, PengurusInti

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def _tulis_csv(folder, baris):
    path = Path(folder) / "foto.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["nama", "foto_path"])
        w.writerows(baris)
    return path


class SeedFungsionarisFotoTests(TestCase):
    def setUp(self):
        self.birdep = BirDep.objects.create(nama="ITF", logo_filename="Logo-ITF.png")
        self.f = Fungsionaris.objects.create(birdep=self.birdep, nama="Muhammad Lanang Zalkifla Harits", jabatan="Ketua Biro ITF")
        self.p = PengurusInti.objects.create(kategori="pi", nama="Yafi Alifuddin", jabatan="Ketua")

    def jalankan(self, path, *args):
        out = StringIO()
        call_command("seed_fungsionaris_foto", str(path), *args, stdout=out)
        return out.getvalue()

    def test_mengisi_kedua_model_lewat_nama(self):
        with TemporaryDirectory() as d:
            path = _tulis_csv(d, [
                ["  muhammad LANANG   zalkifla harits ", "images/fungsionaris/lanang.jpg"],
                ["Yafi Alifuddin", "images/fungsionaris/yafi.jpg"],
            ])
            self.jalankan(path)
        self.f.refresh_from_db(); self.p.refresh_from_db()
        self.assertEqual(self.f.foto_path, "images/fungsionaris/lanang.jpg")
        self.assertEqual(self.p.foto_path, "images/fungsionaris/yafi.jpg")

    def test_dry_run_tidak_menulis(self):
        with TemporaryDirectory() as d:
            self.jalankan(_tulis_csv(d, [["Yafi Alifuddin", "images/fungsionaris/yafi.jpg"]]), "--dry-run")
        self.p.refresh_from_db()
        self.assertEqual(self.p.foto_path, "")

    def test_idempoten_dan_nama_tak_dikenal_dilaporkan(self):
        with TemporaryDirectory() as d:
            path = _tulis_csv(d, [["Yafi Alifuddin", "images/fungsionaris/yafi.jpg"], ["Orang Lain", "images/fungsionaris/x.jpg"]])
            self.jalankan(path)
            keluaran = self.jalankan(path)
        self.assertIn("0 foto_path diperbarui", keluaran)
        self.assertIn("tidak ada di database: Orang Lain", keluaran)

    def test_nama_ganda_atau_path_kosong_ditolak(self):
        with TemporaryDirectory() as d:
            with self.assertRaises(CommandError):
                self.jalankan(_tulis_csv(d, [["A", "x.jpg"], ["a", "y.jpg"]]))
            with self.assertRaises(CommandError):
                self.jalankan(_tulis_csv(d, [["A", ""]]))


class CsvBawaanTests(TestCase):
    def test_setiap_path_menunjuk_ke_berkas_static_yang_ada(self):
        baris = baca_csv(CSV_DEFAULT)
        self.assertTrue(baris)
        for _, nama, path in baris:
            self.assertTrue((STATIC_DIR / path).is_file(), f"{nama}: {path} tidak ada")

    def test_tidak_ada_foto_yatim_di_folder_fungsionaris(self):
        dipakai = {Path(p).name for _, _, p in baca_csv(CSV_DEFAULT)}
        ada = {p.name for p in (STATIC_DIR / "images" / "fungsionaris").iterdir()}
        self.assertEqual(ada, dipakai)


class LogoBirDepTests(TestCase):
    def test_logo_cadangan_adalah_berkas_static_yang_ada(self):
        self.assertTrue((STATIC_DIR / BirDep(nama="Tanpa Logo").logo_url).is_file())


class RenderFotoTests(TestCase):
    def setUp(self):
        self.p = PengurusInti.objects.create(
            kategori="pi", nama="Yafi Alifuddin", jabatan="Ketua", foto_path="images/fungsionaris/yafi.jpg",
        )

    def test_profil_memakai_static_bukan_media(self):
        r = self.client.get("/profil/")
        self.assertContains(r, "/static/images/fungsionaris/yafi.jpg")

    def test_daftar_pengurus_memakai_static(self):
        r = self.client.get(reverse("birdep:pi_list"))
        self.assertContains(r, "/static/images/fungsionaris/yafi.jpg")

    def test_tanpa_foto_path_tidak_ada_img(self):
        PengurusInti.objects.all().update(foto_path="")
        r = self.client.get(reverse("birdep:pi_list"))
        self.assertNotContains(r, "/static/images/fungsionaris/")
