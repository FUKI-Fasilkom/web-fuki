"""
URL configuration for web_fuki project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponseNotFound
from django.urls import include, path
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static

from .sitemaps import SITEMAPS


def protected_submission_media(request, path):
    """Never expose SIWAK task files through Django's DEBUG media helper."""
    return HttpResponseNotFound()

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('main.urls')),
    path('kegiatan/', include('kegiatan.urls')),
    path('team/', include('birdep.urls')),
    path('profil/', include('profil.urls')),
    path('kajian/', include('blog_kajian.urls')),
    path('siwak/', include('siwak.urls')),
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
