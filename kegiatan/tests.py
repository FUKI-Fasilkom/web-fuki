import datetime

from django.core.exceptions import ValidationError
from django.templatetags.static import static
from django.test import TestCase
from django.urls import reverse

from birdep.models import BirDep

from .models import LOGO_FUKI, Kegiatan


class KegiatanRedesignTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        today = datetime.date.today()
        cls.upcoming = Kegiatan.objects.create(
            judul='Kajian mendatang', kategori='kajian',
            tanggal=today + datetime.timedelta(days=7),
            start_time=datetime.time(13), end_time=datetime.time(15),
            lokasi='Fasilkom UI',
        )
        cls.past = Kegiatan.objects.create(
            judul='Kegiatan sebelumnya', kategori='sosial',
            tanggal=today - datetime.timedelta(days=7), lokasi='Fasilkom UI',
        )

    def test_filters_use_event_dates_and_mark_active_tab(self):
        for tab, expected in [('all', 2), ('upcoming', 1), ('past', 1), ('invalid', 2)]:
            with self.subTest(tab=tab):
                response = self.client.get(reverse('kegiatan:home'), {'tab': tab})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '<article ', count=expected)
                self.assertEqual(response.context['active_tab'], 'all' if tab == 'invalid' else tab)
                if tab == 'upcoming':
                    self.assertNotContains(response, self.past.judul)
                if tab == 'past':
                    self.assertNotContains(response, self.upcoming.judul)

    def test_staging_components_and_event_features_are_used(self):
        response = self.client.get(reverse('kegiatan:home'))
        self.assertTemplateUsed(response, 'navbar.html')
        self.assertTemplateUsed(response, 'footer.html')
        self.assertTemplateNotUsed(response, 'components/redesign_navbar.html')
        self.assertContains(response, reverse('siwak:landing'))
        self.assertContains(response, reverse('lapor'))
        self.assertContains(response, 'Kajian &amp; Syiar')
        self.assertContains(response, 'Sosial')
        self.assertContains(response, reverse('kegiatan:detail', args=[self.upcoming.pk]))
        self.assertContains(response, reverse('kegiatan:ics', args=[self.upcoming.pk]))
        self.assertEqual(self.client.get(self.upcoming.get_absolute_url()).status_code, 200)
        calendar = self.client.get(reverse('kegiatan:ics', args=[self.upcoming.pk]))
        self.assertContains(calendar, 'BEGIN:VCALENDAR')
        self.assertIn('attachment;', calendar['Content-Disposition'])

    def test_empty_state(self):
        Kegiatan.objects.all().delete()
        self.assertContains(self.client.get(reverse('kegiatan:home')), 'Belum Ada Kegiatan')


class KegiatanLogoTests(TestCase):
    """Logo penyelenggara menggantikan poster yang dulu diunggah per kegiatan."""

    def buat(self, **extra):
        return Kegiatan.objects.create(
            judul='Kegiatan uji', tanggal=datetime.date.today() + datetime.timedelta(days=3),
            **extra,
        )

    def test_tipe_fuki_memakai_logo_fuki_biru_dan_bercahaya(self):
        kegiatan = self.buat()
        self.assertEqual(kegiatan.tipe, Kegiatan.TIPE_FUKI)
        self.assertEqual(kegiatan.logo_url, static(LOGO_FUKI))
        self.assertEqual(kegiatan.penyelenggara, 'FUKI')
        # Logo FUKI biru di atas kartu navy butuh cahaya gold agar tidak tenggelam.
        self.assertTrue(kegiatan.logo_bercahaya)

    def test_tipe_birdep_memakai_logo_birdepnya(self):
        birdep = BirDep.objects.create(nama='SyiTif', logo_filename='Logo-SyiTif.png')
        kegiatan = self.buat(tipe=Kegiatan.TIPE_BIRDEP, birdep=birdep)
        self.assertEqual(kegiatan.logo_url, static('images/Logo-SyiTif.png'))
        self.assertEqual(kegiatan.penyelenggara, 'SyiTif')
        self.assertFalse(kegiatan.logo_bercahaya)

    def test_birdep_tanpa_berkas_logo_jatuh_ke_logo_fuki_bercahaya(self):
        # Sama dengan kartunya di halaman Biro & Departemen.
        birdep = BirDep.objects.create(nama='Baru', logo_filename='')
        kegiatan = self.buat(tipe=Kegiatan.TIPE_BIRDEP, birdep=birdep)
        self.assertEqual(kegiatan.logo_url, static(LOGO_FUKI))
        self.assertTrue(kegiatan.logo_bercahaya)
        self.assertEqual(kegiatan.penyelenggara, 'Baru')

    def test_tipe_siwak_memakai_gambar_halaman_siwak(self):
        from siwak.models import SiwakInfo

        SiwakInfo.objects.create(apa_itu_gambar='siwak/info/siwak.png')
        kegiatan = self.buat(tipe=Kegiatan.TIPE_SIWAK)
        # URL presigned S3 berganti tanda tangan setiap akses; yang stabil kuncinya.
        self.assertIn('siwak/info/siwak.png', kegiatan.logo_url)
        self.assertEqual(kegiatan.penyelenggara, 'SIWAK')

    def test_tipe_siwak_jatuh_ke_logo_fuki_bila_gambarnya_belum_diunggah(self):
        self.assertEqual(self.buat(tipe=Kegiatan.TIPE_SIWAK).logo_url, static(LOGO_FUKI))

    def test_tipe_birdep_tanpa_birdep_ditolak(self):
        with self.assertRaises(ValidationError):
            self.buat(tipe=Kegiatan.TIPE_BIRDEP).full_clean()

    def test_logo_dirender_di_ketiga_halaman(self):
        birdep = BirDep.objects.create(nama='SosMas', logo_filename='Logo-SosMas.png')
        kegiatan = self.buat(tipe=Kegiatan.TIPE_BIRDEP, birdep=birdep)
        for url in [reverse('kegiatan:home'), kegiatan.get_absolute_url(), reverse('beranda')]:
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), static('images/Logo-SosMas.png'))


class KegiatanFieldOpsionalTests(TestCase):
    """Field opsional yang kosong tidak boleh menyisakan label atau tombol kosong."""

    @classmethod
    def setUpTestData(cls):
        cls.kosong = Kegiatan.objects.create(
            judul='Tanpa detail tambahan',
            tanggal=datetime.date.today() + datetime.timedelta(days=5),
        )
        cls.lengkap = Kegiatan.objects.create(
            judul='Dengan detail lengkap',
            tanggal=datetime.date.today() + datetime.timedelta(days=6),
            start_time=datetime.time(9), end_time=datetime.time(11),
            lokasi='Auditorium Fasilkom UI', contact='0812-0000-0000',
            link_registrasi='https://contoh.test/daftar',
        )

    def test_boleh_disimpan_tanpa_jam_lokasi_contact_dan_link(self):
        self.kosong.full_clean()  # tidak boleh melempar ValidationError

    def test_detail_menyembunyikan_yang_kosong(self):
        kosong = self.client.get(self.kosong.get_absolute_url())
        self.assertNotContains(kosong, 'Daftar Sekarang')
        self.assertNotContains(kosong, 'Auditorium')
        self.assertNotContains(kosong, '0812-0000-0000')
        self.assertContains(kosong, 'Add To Calendar')  # tanggal selalu ada

        lengkap = self.client.get(self.lengkap.get_absolute_url())
        self.assertContains(lengkap, 'Daftar Sekarang')
        self.assertContains(lengkap, 'Auditorium Fasilkom UI')
        self.assertContains(lengkap, '0812-0000-0000')
        self.assertContains(lengkap, '09.00 - 11.00')

    def test_daftar_dan_beranda_menyembunyikan_jam_yang_kosong(self):
        for url in [reverse('kegiatan:home'), reverse('beranda')]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, '09.00 - 11.00')
                self.assertNotContains(response, 'Waktu menyusul')
