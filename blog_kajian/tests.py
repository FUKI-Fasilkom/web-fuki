from datetime import date

from django.test import TestCase
from django.urls import reverse

from .models import Kajian


class BlogKajianPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.article = Kajian.objects.create(
            judul='Kajian Akhlak',
            penceramah='Ustazah Aisyah',
            tanggal=date(2026, 9, 1),
            deskripsi='Menjaga akhlak dalam keseharian.',
        )
        cls.other_article = Kajian.objects.create(
            judul='Kajian Ramadan',
            penceramah='Ustaz Ahmad',
            tanggal=date(2026, 8, 1),
            deskripsi='Persiapan menyambut Ramadan.',
        )

    def test_listing_renders_new_hero_and_article_links(self):
        response = self.client.get(reverse('blog_kajian'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'images/redesign/satin.png')
        self.assertContains(response, 'Kajian Akhlak')
        self.assertContains(response, reverse('kajian_detail', args=[self.article.pk]))

    def test_search_filters_articles_and_can_be_cleared(self):
        response = self.client.get(reverse('blog_kajian'), {'q': 'Aisyah'})
        self.assertContains(response, 'Kajian Akhlak')
        self.assertNotContains(response, 'Kajian Ramadan')
        self.assertContains(response, 'value="Aisyah"')

        empty_response = self.client.get(reverse('blog_kajian'), {'q': 'tidak-ada'})
        self.assertContains(empty_response, 'Kajian tidak ditemukan')
        self.assertContains(empty_response, 'Lihat semua kajian')

    def test_detail_uses_same_design_and_shows_other_articles(self):
        response = self.client.get(reverse('kajian_detail', args=[self.article.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'images/redesign/satin.png')
        self.assertContains(response, 'Menjaga akhlak dalam keseharian.')
        self.assertContains(response, 'Kajian Ramadan')
        self.assertNotContains(response, 'No Image Available')
