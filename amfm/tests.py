import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from siwak.models import MentoringBenefit, TimelineEvent

from .models import AmfmBenefit, AmfmInfo, AmfmTimeline


class BerandaAmfmTests(TestCase):
    def setUp(self):
        self.url = reverse("amfm:beranda")

    def test_halaman_kosong_tetap_tampil_dengan_konten_bawaan(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "components/redesign_header.html")
        self.assertContains(response, "#UnitePurposeAccelerateImpact")
        self.assertContains(response, "Membangun ukhuwah antar angkatan")
        self.assertContains(response, "Benefit AM-FM akan segera diumumkan.")
        # Timeline tanpa tahapan disembunyikan, sama seperti di landing SIWAK.
        self.assertNotContains(response, "Timeline AM-FM")

    def test_benefit_dan_timeline_tampil(self):
        hari_ini = timezone.localdate()
        AmfmBenefit.objects.create(judul="Relasi Lintas Angkatan", deskripsi="Kenal kakak tingkat.")
        AmfmTimeline.objects.create(judul="Pendaftaran Dibuka", deskripsi="Isi formulir online", tanggal_mulai=hari_ini)
        AmfmTimeline.objects.create(judul="Tahap Arsip", tanggal_mulai=hari_ini, is_active=False)

        response = self.client.get(self.url)

        self.assertContains(response, "Relasi Lintas Angkatan")
        self.assertNotContains(response, "Benefit AM-FM akan segera diumumkan.")
        self.assertContains(response, "Timeline AM-FM")
        self.assertContains(response, "Pendaftaran Dibuka")
        self.assertNotContains(response, "Tahap Arsip")

    def test_kedua_tombol_menuju_pendaftaran_yang_dijaga_sso(self):
        response = self.client.get(self.url)

        self.assertContains(response, f'href="{reverse("amfm:daftar")}"', count=2)
        self.assertContains(response, "Daftar Sekarang", count=2)
        self.assertContains(response, 'href="#apa-itu"')
        self.assertContains(response, 'id="apa-itu"')

    def test_riak_tidak_menjulur_melewati_footer(self):
        # Riak setinggi 900px; tanpa pembungkus overflow-hidden ia memanjangkan
        # halaman sehingga muncul bidang putih di bawah footer.
        response = self.client.get(self.url)

        self.assertTemplateUsed(response, "components/riak.html")
        self.assertContains(response, '<div class="relative isolate overflow-hidden bg-[#F9F8F5]">')

    def test_navbar_dan_sitemap_memuat_halaman_amfm(self):
        self.assertContains(self.client.get(reverse("beranda")), f'href="{self.url}"')
        self.assertContains(self.client.get("/sitemap.xml"), f"{self.url}</loc>")

    def test_benefit_dan_timeline_siwak_memakai_komponen_yang_sama(self):
        MentoringBenefit.objects.create(judul="Benefit SIWAK", deskripsi="Isi benefit.")
        TimelineEvent.objects.create(judul="Mentoring 1", deskripsi="Pekan pertama", tanggal_mulai=timezone.localdate())

        response = self.client.get(reverse("siwak:landing"))

        self.assertTemplateUsed(response, "components/benefit_cards.html")
        self.assertTemplateUsed(response, "components/timeline.html")
        self.assertContains(response, "Benefit SIWAK")
        self.assertContains(response, "Mentoring 1")


class SeedAmfmTests(TestCase):
    def test_mengisi_seluruh_konten_dan_aman_dijalankan_ulang(self):
        call_command("seed_amfm", stdout=StringIO())
        nama_gambar = AmfmInfo.get_solo().apa_itu_gambar.name
        call_command("seed_amfm", stdout=StringIO())

        info = AmfmInfo.get_solo()
        self.assertEqual(AmfmInfo.objects.count(), 1)
        self.assertTrue(info.apa_itu_deskripsi)
        self.assertTrue(info.cta_deskripsi)
        # Gambar tidak diunggah ulang setiap kali perintah dijalankan.
        self.assertEqual(info.apa_itu_gambar.name, nama_gambar)
        self.assertEqual(AmfmBenefit.objects.count(), 4)
        self.assertEqual(
            sorted(t.status for t in AmfmTimeline.objects.all()),
            ["completed", "ongoing", "upcoming", "upcoming"],
        )

        response = self.client.get(reverse("amfm:beranda"))
        self.assertContains(response, "Relasi Lintas Angkatan")
        self.assertContains(response, "Timeline AM-FM")
        self.assertContains(response, info.apa_itu_gambar.url)


class AmfmModelTests(TestCase):
    def test_info_selalu_satu_baris(self):
        AmfmInfo.get_solo()
        AmfmInfo(hero_judul="AM-FM 2027").save()
        AmfmInfo.get_solo().save()

        self.assertEqual(AmfmInfo.objects.count(), 1)
        self.assertEqual(AmfmInfo.get_solo().hero_judul, "AM-FM 2027")

    def test_status_timeline_dihitung_dari_tanggal(self):
        hari_ini = timezone.localdate()
        sehari = datetime.timedelta(days=1)
        kasus = [
            (hari_ini - 2 * sehari, None, "completed", "Completed"),
            (hari_ini - 2 * sehari, hari_ini - sehari, "completed", "Completed"),
            (hari_ini, None, "ongoing", "Ongoing"),
            (hari_ini - sehari, hari_ini + sehari, "ongoing", "Ongoing"),
            (hari_ini + sehari, None, "upcoming", "Upcoming"),
        ]
        for mulai, selesai, status, label in kasus:
            with self.subTest(mulai=mulai, selesai=selesai):
                tahap = AmfmTimeline(judul="Tahap", tanggal_mulai=mulai, tanggal_selesai=selesai)
                self.assertEqual(tahap.status, status)
                self.assertEqual(tahap.status_label, label)
