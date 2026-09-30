"""Halaman "Akses Ditolak" bersama untuk setiap bagian SIWAK yang dijaga peran.

Ada empat bagian berpenjaga: panel pengurus (`staf_required`), portal mentor
(`services.mentor.require_mentor`), pemindai QR (`pemindai_required`), dan
Tugas Mentoring (`mentee_required`). Ketiga decorator itu tinggal di sini. User yang sudah login tapi salah peran
tidak lagi mendapat 403 polos: penjaganya melempar `AksesDitolak(bagian)`, dan
`handler403` merender satu halaman bergaya SIWAK yang menyebut halaman mana
yang tertutup dan menawarkan jalan ke bagian miliknya sendiri (mis. mentor
yang membuka panel diarahkan ke portal mentor).

`AksesDitolakMiddleware` merender `AksesDitolak` lebih dulu supaya log tidak
penuh traceback; `handler403` (dipasang di `web_fuki/urls.py`) menangkap
PermissionDenied lainnya dengan halaman yang sama.

Status HTTP-nya tetap 403 — yang berubah hanya tampilannya.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse

from .models import Profile, SiwakInfo
from .services.pemindai import boleh_memindai

# bagian -> (nama halaman di kalimat penolakan, label tombol, nama URL berandanya)
BAGIAN = {
    "admin": ("Admin Panel SIWAK", "Admin Panel", "siwak:panel_beranda"),
    "pemindai": ("Pemindai QR", "Pemindai QR", "siwak:pindai_beranda"),
    "mentee": ("Tugas Mentoring", "Tugas Mentoring", "siwak:tugas_list"),
    "mentor": ("Mentor", "Portal Mentor", "siwak:mentor_dashboard"),
}


class AksesDitolak(PermissionDenied):
    """PermissionDenied yang tahu bagian mana yang ditolak, supaya
    `handler403` bisa menulis pesan yang tepat."""

    def __init__(self, bagian):
        self.bagian = bagian
        super().__init__(f"Anda tidak memiliki akses ke halaman {BAGIAN[bagian][0]}.")


def bagian_utama(user):
    """Bagian SIWAK tempat `user` bekerja, atau None kalau tidak punya.

    Urutannya sama dengan `sso.role_landing_url` (yang memakai fungsi ini):
    pengurus lebih dulu karena superuser juga lolos `boleh_memindai()`.
    """
    if not user or not user.is_authenticated:
        return None
    if user.is_staff:
        return "admin"
    if boleh_memindai(user):
        return "pemindai"
    role = Profile.objects.filter(user=user).values_list("role", flat=True).first()
    return {Profile.ROLE_MENTEE: "mentee", Profile.ROLE_MENTOR: "mentor"}.get(role)


def url_bagian(bagian):
    return reverse(BAGIAN[bagian][2])


# ---------------------------------------------------------------------------
# Penjaga peran
#
# `user_passes_test` Django mengarahkan *setiap* user yang gagal ke halaman
# login — termasuk yang sudah login tapi salah peran — sehingga halaman login
# berputar-putar. Penjaga di bawah meniru `staff_member_required`: user anonim
# ke halaman login yang tepat, user yang salah peran ke halaman 403 di atas.
# ---------------------------------------------------------------------------

def staf_required(view_func):
    """Panel pengurus: hanya `is_staff`. Yang belum login ke login admin.

    Akun pemindai QR sengaja selalu `is_staff=False` (lihat AkunPemindaiForm),
    jadi decorator inilah yang menutup seluruh panel untuknya."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated:
            if not request.user.is_staff:
                raise AksesDitolak("admin")
            return view_func(request, *args, **kwargs)
        return redirect_to_login(request.get_full_path(), reverse("admin:login"))

    return _wrapped


def pemindai_required(view_func):
    """Pemindai QR: superuser dan akun panitia yang punya salah satu izin pindai.

    Yang belum login ke "Login Akun Khusus" (login admin menolak akun panitia,
    karena bukan staf). Jenis QR mana yang boleh dipindai diperiksa di dalam
    `qr_verify`, begitu payload bertanda tangan menyebut jenisnya.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated:
            if not boleh_memindai(request.user):
                raise AksesDitolak("pemindai")
            return view_func(request, *args, **kwargs)
        return redirect_to_login(request.get_full_path(), reverse("siwak:login_khusus"))

    return _wrapped


def mentee_required(view_func):
    """Halaman Tugas Mentoring: harus login DAN berperan Mentee.

    User yang sudah punya bagiannya sendiri (mentor, pengurus, pemindai QR)
    mendapat halaman 403 yang menunjuk ke bagian itu. Sisanya (anonim, role
    NULL) dikembalikan ke /siwak dengan notifikasi, bukan ke login/403, supaya
    user tahu harus menghubungi CP.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated:
            if Profile.objects.filter(user=request.user, role=Profile.ROLE_MENTEE).exists():
                return view_func(request, *args, **kwargs)
            if bagian_utama(request.user):
                raise AksesDitolak("mentee")
        messages.error(request, "Anda harus menjadi Mentee, hubungi CP SIWAK")
        return redirect("siwak:landing")

    return _wrapped


class AksesDitolakMiddleware:
    """Merender `AksesDitolak` sebelum sampai ke penangan exception Django.

    Tanpa ini setiap kunjungan salah peran dicatat `django.request` sebagai
    WARNING lengkap dengan traceback; ini kejadian biasa, bukan galat. Respons
    403 yang dikembalikan di sini tetap tercatat satu baris "Forbidden: ...".
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, AksesDitolak):
            return handler403(request, exception)
        return None


def handler403(request, exception=None):
    """Pengganti halaman 403 bawaan Django untuk seluruh situs.

    Pesan exception hanya ditampilkan untuk `AksesDitolak`; PermissionDenied
    lain (termasuk dari admin Django) bisa membawa teks internal, jadi cukup
    kalimat umum.
    """
    milik = bagian_utama(request.user)
    konteks = {
        "pesan": (
            str(exception) if isinstance(exception, AksesDitolak)
            else "Anda tidak memiliki akses ke halaman ini."
        ),
        "info": SiwakInfo.get_solo(),
    }
    if milik:
        konteks["tujuan_url"] = url_bagian(milik)
        konteks["tujuan_label"] = f"Pergi ke {BAGIAN[milik][1]}"
    else:
        konteks["tujuan_url"] = reverse("siwak:landing")
        konteks["tujuan_label"] = "Kembali ke SIWAK-NG"
    return render(request, "siwak/akses_ditolak.html", konteks, status=403)
