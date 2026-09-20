"""Jalur login non-SSO untuk mentor (PRD 7 - Authentication).

SIWAK punya dua pintu masuk sekarang:

  * SSO UI CAS — untuk mentee dan mentor yang punya akun SSO aktif. Seluruh
    alurnya ada di `siwak/sso.py` dan tidak disentuh dari sini.
  * Akun lokal — untuk mentor yang tidak punya SSO UI aktif. Akunnya dibuat
    pengelola di panel (`MentorLokalForm`), dan hanya profil ber-role mentor
    dengan `auth_source="lokal"` yang boleh lewat sini.

`login_pilihan` adalah halaman yang mempertemukan keduanya, dan itulah yang
dipakai `LOGIN_URL` supaya mentor anonim tidak lagi langsung dilempar ke CAS.
"""

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render, resolve_url
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Profile, SiwakInfo
from .sso import role_landing_url


def _next_yang_aman(request):
    """`?next=` yang boleh dipakai, atau "" kalau tidak ada/tidak tepercaya."""
    tujuan = request.GET.get("next") or request.POST.get("next") or ""
    if tujuan and url_has_allowed_host_and_scheme(
        tujuan, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return tujuan
    return ""


def login_pilihan(request):
    """Halaman pemilih metode login: SSO UI atau akun mentor lokal.

    `next` diteruskan ke kedua tautan — tanpa itu deep link yang membawa orang
    ke sini lewat @login_required hilang begitu dia memilih metodenya.
    """
    if request.user.is_authenticated:
        return redirect(_next_yang_aman(request) or role_landing_url(request.user))

    return render(request, "siwak/auth/login_pilihan.html", {
        "next": _next_yang_aman(request),
        "url_sso": reverse("siwak:cas_ng_login"),
        "url_mentor": reverse("siwak:mentor_login"),
        # Link CP-nya diatur pengelola lewat panel (SiwakInfo.kontak_cp), sama
        # dengan yang dipakai halaman "Cari Kelompok".
        "info": SiwakInfo.get_solo(),
    })


class MentorLoginForm(AuthenticationForm):
    """Form login lokal, dibatasi hanya untuk mentor non-SSO.

    Tanpa pembatasan ini setiap `User` berpassword valid — termasuk akun staf —
    bisa memakai halaman ini. `ModelBackend` yang mengautentikasi (CASBackend
    bersignature `(request, ticket, service)` sehingga `authenticate()`
    melewatinya untuk kredensial username/password), jadi penyaringnya harus di
    lapisan form.
    """

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)

        boleh = Profile.objects.filter(
            user=user,
            role=Profile.ROLE_MENTOR,
            auth_source=Profile.SOURCE_LOKAL,
        ).exists()
        if not boleh:
            raise self.get_invalid_login_error()


class MentorLoginView(LoginView):
    """LoginView biasa dengan form terbatas dan tujuan yang sadar role."""

    template_name = "siwak/auth/login_mentor.html"
    authentication_form = MentorLoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        # `role_landing_url` sudah dipakai jalur SSO; jangan tulis ulang aturan
        # tujuan per role di dua tempat.
        return _next_yang_aman(self.request) or role_landing_url(self.request.user)


def logout_cerdas(request):
    """Logout yang mengikuti cara orangnya masuk.

    Akun SSO harus lewat logout CAS supaya sesi di sso.ui.ac.id ikut bersih
    (`CAS_LOGOUT_COMPLETELY` default-nya True). Akun lokal tidak punya sesi di
    sana, jadi mengirimnya ke server CAS hanya membingungkan.
    """
    backend = request.session.get(BACKEND_SESSION_KEY, "")
    if backend.endswith("CASBackend"):
        return redirect("siwak:cas_ng_logout")

    logout(request)
    return redirect(resolve_url(getattr(settings, "CAS_LOGOUT_NEXT_PAGE", "/")))
