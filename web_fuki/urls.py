"""URLconf utama: setiap app di-include di bawah prefiksnya sendiri."""
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponseNotFound
from django.urls import include, path
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static

from .sitemaps import SITEMAPS


def protected_submission_media(request, path):
    """Never expose SIWAK task files through Django's DEBUG media helper.

    They are only reachable through `siwak:answer_download`, which checks that
    the viewer is the owner, the mentee's mentor, or staff.
    """
    return HttpResponseNotFound()


# Halaman 403 bergaya SIWAK yang menunjukkan jalan ke bagian milik user sendiri.
handler403 = 'siwak.akses.handler403'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('main.urls')),
    path('kegiatan/', include('kegiatan.urls')),
    path('team/', include('birdep.urls')),
    path('profil/', include('profil.urls')),
    path('kajian/', include('blog_kajian.urls')),
    path('siwak/', include('siwak.urls')),
    # Lampiran jawaban tugas (siwak/jawaban/, dan siwak/tugas/ dari versi lama).
    path('media/siwak/jawaban/<path:path>', protected_submission_media),
    path('media/siwak/tugas/<path:path>', protected_submission_media),

    # SEO: dua berkas yang dicari perayap di akar domain.
    path(
        'sitemap.xml',
        sitemap,
        {'sitemaps': SITEMAPS},
        name='django.contrib.sitemaps.views.sitemap',
    ),
    path(
        'robots.txt',
        TemplateView.as_view(template_name='robots.txt', content_type='text/plain'),
        name='robots',
    ),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
