"""Authentication helper for the SIWAK section (PRD 7 - Authentication).

PRD 7 says login is "Menggunakan SSO UI" (Universitas Indonesia's central CAS
SSO at https://sso.ui.ac.id/cas2/). Wiring up the *real* SSO UI requires two
things this environment cannot provide on its own:

  1. The FUKI website registered as an official "service" with UI's SSO/PPSI
     team (they whitelist the callback URL).
  2. A CAS client library talking to that server (e.g. `django-cas-ng`).

So this module implements the same shape a real CAS login would have — a
"login" entrypoint that resolves to a Django `User` + `MahasiswaProfile`, after
which every other authorized feature (tugas, RSVP, QR) works identically —
but the entrypoint itself is a simple NPM + Nama + Jurusan form instead of a
redirect to sso.ui.ac.id. That keeps the swap to real SSO a small, isolated
change instead of a rewrite. See the bottom of this file for that swap.
"""

from django.contrib.auth import get_user_model
from django.contrib import messages
from django.db import transaction

from .models import MahasiswaProfile


from django.dispatch import receiver
from django_cas_ng.signals import cas_user_authenticated
from cas import CASClientV2
from lxml import etree

User = get_user_model()


# ---------------------------------------------------------------------------
# SSO UI XML parsing tolerance
#
# Akar masalah login yang gagal ternyata bukan XML serviceValidate yang rusak:
# nginx di depan `sso.ui.ac.id` menolak User-Agent default `python-requests/*`
# dan membalas HTTP 400 dengan halaman HTML (ada tag <hr> yang tidak ditutup),
# sehingga parser python-cas melempar `ParseError: mismatched tag`. Perbaikan
# primer ada di `CAS_SESSION_FACTORY` (settings.py) yang memakai User-Agent
# browser. Shim ini tetap kita pertahankan sebagai pengaman: selain tahan
# terhadap XML yang tidak seimbang, ia juga mengenali wrapper atribut `<info>`
# yang dipakai SSO UI (python-cas hanya membaca `<attributes>`/`<norEduPerson>`).
# Respons mentah tetap terlihat lewat log DEBUG logger "cas" (settings.py).
# ---------------------------------------------------------------------------

CAS_NAMESPACE = "http://www.yale.edu/tp/cas"
_ATTRIBUTE_WRAPPER_TAGS = {"attributes", "norEduPerson", "info"}


def _put_attribute(attributes, name, value):
    if name in attributes:
        if isinstance(attributes[name], list):
            attributes[name].append(value)
        else:
            attributes[name] = [attributes[name], value]
    else:
        attributes[name] = value


def _parse_response_xml(response):
    """Tolerant twin of cas.CASClientV2.parse_response_xml.

    Returns the same (user, attributes, pgtiou) triple, but parses with lxml in
    `recover` mode so SSO UI's stray closing tag no longer raises ParseError.
    """
    parser = etree.XMLParser(recover=True)
    tree = etree.fromstring(response, parser=parser)
    if tree is None:
        return None, {}, None

    user = None
    attributes = {}
    pgtiou = None

    success = tree.find(f"{{{CAS_NAMESPACE}}}authenticationSuccess")
    if success is None:
        return user, attributes, pgtiou

    user_el = success.find(f"{{{CAS_NAMESPACE}}}user")
    if user_el is not None and user_el.text:
        user = user_el.text.strip()

    for element in success:
        local = etree.QName(element).localname
        if element.tag.endswith("proxyGrantingTicket"):
            pgtiou = element.text
        elif local in _ATTRIBUTE_WRAPPER_TAGS:
            for attribute in element:
                _put_attribute(attributes, etree.QName(attribute).localname, attribute.text)
        elif local not in ("user", "attraStyle"):
            _put_attribute(attributes, local, element.text)

    return user, attributes, pgtiou


def _apply_ui_sso_xml_patch():
    """Swaps python-cas' strict stdlib parse for the lxml recover twin."""
    CASClientV2.parse_response_xml = staticmethod(_parse_response_xml)


_apply_ui_sso_xml_patch()

# TODO: verifikasi mapping ini dengan mapping yang asli. assume the program mapping is true
KD_ORG_PROGRAM_MAP = {
    "01": "IK",
    "02": "IK-IUP",
    "06": "SI",
    "10": "KA",
}

@receiver(cas_user_authenticated)
def handle_cas_login(sender, user, username, attributes, **kwargs):
    attributes = attributes or {}

    npm = get_attribute(attributes, "npm")
    nama_lengkap = get_attribute(attributes, "nama")
    kd_org = get_attribute(attributes, "kd_org")
    angkatan = f"20{npm[:2]}" if len(npm) >= 2 and npm[:2].isdigit() else ""

    if not npm:
        raise ValueError("SSO tidak memberikan NPM")
    if not nama_lengkap:
        raise ValueError("SSO tidak memberikan nama lengkap")
    if not kd_org:
        raise ValueError("SSO tidak memberikan kode jurusan")

    program_code = kd_org.split('.')[0]
    jurusan = KD_ORG_PROGRAM_MAP.get(program_code)

    if not jurusan:
        raise ValueError(f"Kode program tidak dikenal: {program_code}")

    sync_mahasiswa_profile(
        user=user,
        npm=npm,
        nama_lengkap=nama_lengkap,
        jurusan=jurusan,
        angkatan=angkatan
    )

    request = kwargs.get("request")
    if request:
        messages.success(request, f"Login berhasil. Selamat datang, {nama_lengkap}.")


@transaction.atomic
def sync_mahasiswa_profile(
    *, user, npm: str, nama_lengkap: str, jurusan: str, angkatan: str = ""
) -> MahasiswaProfile:
    """Satukan data SSO dengan MahasiswaProfile.

    Profil dicari dalam tiga langkah, dan urutannya menentukan:

    1. Profil milik akun ini sendiri — selalu menang, supaya satu akun tidak
       pernah berakhir punya dua profil.
    2. Profil ber-NPM sama yang *belum* dipegang akun mana pun — inilah baris
       yang dibuat pengelola di panel SIWAK sebelum orangnya pernah login, dan
       inilah yang diklaim sekarang. Profil yang sudah ada pemiliknya sengaja
       dilewati supaya tidak bisa direbut.
    3. Kalau tidak ada keduanya, profil baru (mentee, tanpa kelompok).

    `role` dan `kelompok` sengaja TIDAK disentuh di sini. Pengelola yang
    menyiapkan baris berperan mentor lebih dulu, misalnya, tetap mentor setelah
    orangnya login; penempatan kelompok juga tidak hilang saat login ulang.
    """
    profile = (
        MahasiswaProfile.objects.filter(user=user).first()
        or MahasiswaProfile.objects.filter(npm=npm, user__isnull=True).first()
        or MahasiswaProfile(npm=npm)
    )

    profile.user = user
    profile.npm = npm
    profile.nama_lengkap = nama_lengkap
    profile.jurusan = jurusan
    profile.angkatan = angkatan
    profile.save()
    return profile

def get_attribute(attributes, key):
    value = attributes.get(key, "")

    if isinstance(value, (list, tuple)):
        return value[0].strip() if value else ""

    return str(value).strip()



# ---------------------------------------------------------------------------
# Swapping in real SSO UI later:
#
# 1. `pip install django-cas-ng` and add `django_cas_ng` to INSTALLED_APPS.
# 2. In settings.py:
#        CAS_SERVER_URL = "https://sso.ui.ac.id/cas2/"
#        AUTHENTICATION_BACKENDS = [
#            "django_cas_ng.backends.CASBackend",
#            "django.contrib.auth.backends.ModelBackend",
#        ]
# 3. Add to urls.py:
#        path("siwak/sso-login/", cas_views.LoginView.as_view(), name="cas_ng_login"),
#        path("siwak/sso-logout/", cas_views.LogoutView.as_view(), name="cas_ng_logout"),
# 4. Replace the body of `MabaLoginView` in siwak/views.py with a redirect to
#    `cas_ng_login`, and connect the `django_cas_ng.signals.cas_user_authenticated`
#    signal to a receiver that calls the same get_or_create logic above using
#    the NPM/nama/jurusan attributes UI's CAS response provides.
# ---------------------------------------------------------------------------
