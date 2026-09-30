"""Login SSO UI (CAS) untuk SIWAK (PRD 7 - Authentication).

`django-cas-ng` menangani protokol CAS ke https://sso.ui.ac.id/cas2/ (lihat
blok autentikasi di settings.py). Modul ini berisi bagian yang khas SSO UI:

  * parser serviceValidate yang toleran terhadap respons SSO UI;
  * `handle_cas_login`, penerima sinyal `cas_user_authenticated` yang
    menyinkronkan `Profile` dari atribut CAS (npm, nama, kd_org);
  * `role_landing_url` dan `RoleRedirectLoginView`, tujuan sesudah login.

Pintu login kedua (Akun Khusus, username + password) ada di auth_views.py.
"""

from cas import CASClientV2
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.dispatch import receiver
from django.shortcuts import resolve_url
from django_cas_ng.signals import cas_user_authenticated
from django_cas_ng.views import LoginView
from lxml import etree

from .akses import bagian_utama, url_bagian
from .models import EventRSVP, Profile
from .services.rsvp import klaim_rsvp_tertunda


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

# Kode program studi (awal `kd_org` dari SSO UI) -> JURUSAN_CHOICES.
# TODO: verifikasi mapping ini dengan mapping resmi SSO UI.
KD_ORG_PROGRAM_MAP = {
    "01": "IK",
    "02": "IK-IUP",
    "06": "SI",
    "10": "KA",
}

@receiver(cas_user_authenticated)
def handle_cas_login(sender, user, username, attributes, **kwargs):
    attributes = attributes or {}

    # Jaring pengaman untuk tabrakan akun. CAS mencocokkan User lewat username,
    # sedangkan profil diklaim lewat NPM — kalau sebuah username SSO kebetulan
    # sama dengan username akun lokal, login ini akan mendarat di akun mentor
    # non-SSO dan menimpa identitasnya. Awalan `mentor-` membuatnya praktis
    # mustahil; ini penjaga terakhirnya.
    if Profile.objects.filter(user=user, auth_source=Profile.SOURCE_LOKAL).exists():
        raise ValueError(
            "Akun ini terdaftar sebagai mentor non-SSO. Masuk lewat Login Akun "
            "Khusus, bukan SSO UI."
        )
    # Penjaga yang sama untuk akun panitia SIWAK (pemindai QR) buatan panel:
    # tanpa profil sama sekali, jadi yang bisa dikenali hanya awalan username-nya.
    if user.username.startswith(EventRSVP.USERNAME_PEMINDAI_PREFIX):
        raise ValueError(
            "Akun ini terdaftar sebagai akun panitia SIWAK (pemindai QR). Masuk lewat Login Akun "
            "Khusus, bukan SSO UI."
        )

    npm = get_attribute(attributes, "npm")
    nama_lengkap = get_attribute(attributes, "nama")
    kd_org = get_attribute(attributes, "kd_org")

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

    # Dua digit pertama NPM adalah tahun masuk.
    angkatan = f"20{npm[:2]}" if len(npm) >= 2 and npm[:2].isdigit() else ""

    sync_profile(
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
def sync_profile(
    *, user, npm: str, nama_lengkap: str, jurusan: str, angkatan: str = ""
) -> Profile:
    """Satukan data SSO dengan Profile.

    Profil dicari dalam tiga langkah, dan urutannya menentukan:

    1. Profil milik akun ini sendiri — selalu menang, supaya satu akun tidak
       pernah berakhir punya dua profil.
    2. Profil ber-NPM sama yang *belum* dipegang akun mana pun — inilah baris
       yang dibuat pengelola di panel SIWAK sebelum orangnya pernah login, dan
       inilah yang diklaim sekarang. Profil yang sudah ada pemiliknya sengaja
       dilewati supaya tidak bisa direbut, begitu pula profil akun lokal.
    3. Kalau tidak ada keduanya, profil baru tanpa role dan tanpa kelompok.

    `role` dan `kelompok` sengaja TIDAK disentuh di sini. Akun yang baru login
    tetap tanpa role (NULL) sampai pengelola memilih Mentee atau Mentor di
    daftar Profile panel SIWAK. Pengelola yang menyiapkan baris berperan mentor
    lebih dulu, misalnya, tetap mentor setelah orangnya login; penempatan
    kelompok juga tidak hilang saat login ulang.
    """
    profile = (
        Profile.objects.filter(user=user).first()
        # `auth_source` eksplisit walau mentor non-SSO ber-NPM NULL dan selalu
        # punya `user`: dua-duanya sudah menyingkirkannya dari cabang ini, dan
        # filter ini yang menuliskan niatnya.
        or Profile.objects.filter(
            npm=npm, user__isnull=True, auth_source=Profile.SOURCE_SSO
        ).first()
        or Profile(npm=npm)
    )

    profile.user = user
    profile.npm = npm
    profile.nama_lengkap = nama_lengkap
    profile.jurusan = jurusan
    profile.angkatan = angkatan
    profile.save()
    # RSVP yang sudah masuk lewat form lain (seed_rsvp) baru bisa jadi EventRSVP
    # setelah orangnya punya akun.
    klaim_rsvp_tertunda(profile)
    return profile

def role_landing_url(user):
    """Tujuan default setelah login, untuk pintu SSO maupun Akun Khusus.

    Urutannya menentukan: pengurus (`is_staff`) -> panel SIWAK, akun yang boleh
    memindai QR -> halaman pemindai, mentee -> daftar tugas, mentor -> dashboard
    mentor, selain itu (role NULL, belum punya profil, dst.) -> beranda FUKI.

    Pengurus didahulukan karena superuser juga lolos `boleh_memindai()`; tanpa
    urutan ini dia mendarat di halaman pemindai, bukan di panelnya. Yang
    diperiksa `is_staff`, bukan `is_superuser`, karena itulah syarat panelnya.

    Urutannya tinggal di `akses.bagian_utama`, yang juga dipakai halaman 403
    untuk menawarkan jalan ke bagian milik user sendiri.
    """
    bagian = bagian_utama(user)
    return url_bagian(bagian) if bagian else "/"


class RoleRedirectLoginView(LoginView):
    """LoginView CAS yang mengarahkan user berdasarkan role setelah login.

    `?next=` eksplisit (mis. dari @login_required) tetap dihormati supaya deep
    link tidak hilang; tanpa itu, tujuan ditentukan `role_landing_url`.

    django-cas-ng selalu menyisipkan `next=CAS_REDIRECT_URL` ke service URL, jadi
    saat callback SSO `?next=` selalu ada. Nilai yang sama dengan default itu
    dianggap "tidak ada next" — kalau tidak, role tidak pernah dipakai.
    """

    def successful_login(self, request, next_page):
        explicit_next = request.GET.get("next")
        if not explicit_next or explicit_next == resolve_url(settings.CAS_REDIRECT_URL):
            next_page = role_landing_url(request.user)
        return super().successful_login(request, next_page)


def get_attribute(attributes, key):
    """Satu atribut CAS sebagai string; atribut bernilai banyak diambil yang pertama."""
    value = attributes.get(key, "")

    if isinstance(value, (list, tuple)):
        return value[0].strip() if value else ""

    return str(value).strip()
