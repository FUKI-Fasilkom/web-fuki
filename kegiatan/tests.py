import datetime

from django.test import TestCase
from django.urls import reverse

from .models import Kegiatan


class KegiatanRedesignTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        today = datetime.date.today()
        cls.upcoming = Kegiatan.objects.create(
            judul='Kajian mendatang', kategori='kajian',
            tanggal=today + datetime.timedelta(days=7),
            start_time=datetime.time(13), end_time=datetime.time(15),
            lokasi='Fasilkom UI', gambar='kegiatan/poster.jpg',
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
        # S3 presigned URLs can receive a different timestamp/signature on each
        # access. Assert the stable object key rendered inside that URL.
        self.assertContains(response, self.upcoming.gambar.name)
        self.assertContains(response, reverse('kegiatan:detail', args=[self.upcoming.pk]))
        self.assertContains(response, reverse('kegiatan:ics', args=[self.upcoming.pk]))
        self.assertEqual(self.client.get(self.upcoming.get_absolute_url()).status_code, 200)
        calendar = self.client.get(reverse('kegiatan:ics', args=[self.upcoming.pk]))
        self.assertContains(calendar, 'BEGIN:VCALENDAR')
        self.assertIn('attachment;', calendar['Content-Disposition'])

    def test_empty_state(self):
        Kegiatan.objects.all().delete()
        self.assertContains(self.client.get(reverse('kegiatan:home')), 'Belum Ada Kegiatan')
