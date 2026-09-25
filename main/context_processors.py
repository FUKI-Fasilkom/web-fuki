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
    # Satu aturan berbasis awalan alamat, bukan blok yang ditimpa per templat:
    # halaman internal baru di bawah awalan yang sama otomatis ikut tanpa
    # Clarity, tanpa harus ingat menimpa apa pun. Lihat
    # CLARITY_EXCLUDED_PREFIXES di settings.py.
    return {
        'CLARITY_AKTIF': not request.path.startswith(settings.CLARITY_EXCLUDED_PREFIXES),
    }
