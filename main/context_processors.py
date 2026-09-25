"""Context processor SEO dan monitoring.

`seo` menyediakan konstanta situs ke seluruh template supaya
`templates/base.html` bisa menyusun <title>, meta description, canonical, Open
Graph, dan JSON-LD tanpa nilai yang ditulis ulang di tiap halaman. Nilainya
berasal dari settings.py (lihat blok "SEO" di sana).

`monitoring` menentukan apakah halaman ini boleh memuat Microsoft Clarity.
"""

from django.conf import settings
from django.templatetags.static import static


def seo(request):
    # static() dipanggil di sini, bukan di settings, karena butuh STATIC_URL
    # yang sudah final (WhiteNoise menambahkan hash pada nama berkas di produksi).
    og_image = static(settings.SITE_OG_IMAGE)
    if not og_image.startswith('http'):
        og_image = f"{settings.SITE_URL}{og_image}"

    return {
        'SITE_NAME': settings.SITE_NAME,
        'SITE_URL': settings.SITE_URL,
        'SITE_TITLE': settings.SITE_TITLE,
        'SITE_DESCRIPTION': settings.SITE_DESCRIPTION,
        'SITE_OG_IMAGE': og_image,
        'SITE_SOCIAL_PROFILES': settings.SITE_SOCIAL_PROFILES,
        'GOOGLE_SITE_VERIFICATION': settings.GOOGLE_SITE_VERIFICATION,
    }


def monitoring(request):
    # Clarity merekam sesi, termasuk teks halaman, jadi hanya untuk tamu
    # (belum login) di production. Siapa pun yang sudah login bisa melihat data
    # mahasiswa lain atau datanya sendiri, dan staging/lokal tidak perlu direkam.
    # CLARITY_EXCLUDED_PREFIXES tetap dicek sebagai jaring kedua. `path_info`,
    # bukan `path`, supaya awalan tetap cocok kalau situs dipasang di bawah
    # SCRIPT_NAME.
    user = getattr(request, 'user', None)
    return {
        'CLARITY_AKTIF': (
            settings.DEPLOY_ENV == 'production'
            and not (user is not None and user.is_authenticated)
            and not request.path_info.startswith(settings.CLARITY_EXCLUDED_PREFIXES)
        ),
    }
