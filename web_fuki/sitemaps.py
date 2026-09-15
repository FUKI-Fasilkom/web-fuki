"""Peta situs untuk /sitemap.xml.

Dipakai Google untuk menemukan seluruh halaman tanpa harus menelusuri tautan
satu per satu. Sengaja tidak memakai `django.contrib.sites`: kerangka sitemap
Django jatuh ke RequestSite (host dari request) bila app itu tidak terpasang,
sehingga tidak ada tabel dan migrasi tambahan yang perlu diurus.
"""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from birdep.models import BirDep, PengurusInti
from blog_kajian.models import Kajian


class StaticViewSitemap(Sitemap):
    """Halaman yang URL-nya tetap."""

    changefreq = 'weekly'
    protocol = 'https'

    def items(self):
        # (path, prioritas). Beranda ditulis literal, bukan lewat reverse():
        # main/urls.py mendaftarkan nama 'beranda' dua kali sehingga
        # reverse('beranda') mengembalikan '/beranda', bukan '/'.
        return [
            ('/', 1.0),
            (reverse('profil'), 0.9),
            (reverse('kegiatan:home'), 0.8),
            (reverse('kegiatan:kegiatan_all'), 0.7),
            (reverse('kegiatan:kegiatan_upcoming'), 0.7),
            (reverse('kegiatan:kegiatan_past'), 0.5),
            (reverse('blog_kajian'), 0.8),
            (reverse('birdep:team_list'), 0.8),
            (reverse('birdep:pi_list'), 0.6),
            (reverse('birdep:ki_list'), 0.6),
            (reverse('birdep:mdc_list'), 0.6),
            (reverse('siwak:landing'), 0.7),
            (reverse('siwak:kelompok_search'), 0.5),
            (reverse('hubungi_kami'), 0.6),
        ]

    def location(self, item):
        return item[0]

    def priority(self, item):
        return item[1]


class KajianSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.7
    protocol = 'https'

    def items(self):
        return Kajian.objects.all()

    def location(self, obj):
        return reverse('kajian_detail', kwargs={'id': obj.id})

    def lastmod(self, obj):
        return obj.updated_at


class BirDepSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.6
    protocol = 'https'

    def items(self):
        return BirDep.objects.filter(is_active=True)

    def location(self, obj):
        # Bukan obj.get_absolute_url(): method itu me-reverse
        # 'main:birdep_tentang', namespace yang tidak ada (yang benar 'birdep').
        return reverse('birdep:birdep_tentang', kwargs={'slug': obj.slug})

    def lastmod(self, obj):
        return obj.updated_at


class PengurusSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.5
    protocol = 'https'

    def items(self):
        return PengurusInti.objects.filter(is_active=True).exclude(slug='')

    def location(self, obj):
        return reverse('birdep:pi_detail', kwargs={'slug': obj.slug})

    def lastmod(self, obj):
        return obj.updated_at


SITEMAPS = {
    'halaman': StaticViewSitemap,
    'kajian': KajianSitemap,
    'birdep': BirDepSitemap,
    'pengurus': PengurusSitemap,
}
