from django.test import TestCase
from django.urls import resolve, reverse

from birdep.models import BirDep
from web_fuki.urls import protected_submission_media


class BerandaUrlTests(TestCase):
    def test_nama_beranda_menunjuk_ke_alamat_kanonis(self):
        # '/beranda' tetap dilayani, tapi tautan yang dibuat lewat nama rute
        # harus mengarah ke '/', alamat yang dinyatakan canonical.
        self.assertEqual(reverse('beranda'), '/')
        self.assertEqual(self.client.get('/beranda').status_code, 200)

    def test_navbar_dan_404_menaut_ke_alamat_kanonis(self):
        self.assertContains(self.client.get('/kegiatan/'), 'href="/"')
        self.assertContains(self.client.get('/tidak-ada/'), 'href="/"', status_code=404)


class SitemapTests(TestCase):
    def test_memuat_beranda_dan_halaman_birdep(self):
        birdep = BirDep.objects.create(nama='ITF', logo_filename='Logo-ITF.png')
        self.assertEqual(birdep.get_absolute_url(), f'/team/{birdep.slug}/tentang/')

        response = self.client.get('/sitemap.xml')
        self.assertContains(response, '/team/itf/tentang/</loc>')
        self.assertContains(response, '://testserver/</loc>')


class LampiranTugasTidakTerbukaTests(TestCase):
    """Lampiran jawaban tugas hanya boleh diunduh lewat siwak:answer_download."""

    def test_folder_lampiran_tugas_ditangkap_sebelum_media_debug(self):
        # Tes berjalan dengan DEBUG=False, jadi static() tidak memasang apa pun
        # dan 404 saja tidak membuktikan apa-apa. Yang diperiksa: kedua folder
        # lampiran ditangkap view penolak, yang terdaftar sebelum static().
        for path in ('/media/siwak/jawaban/a.pdf', '/media/siwak/tugas/1/2/a.pdf'):
            with self.subTest(path=path):
                self.assertIs(resolve(path).func, protected_submission_media)
