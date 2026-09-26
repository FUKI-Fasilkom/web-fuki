"""Jalur login non-SSO "Akun Khusus" (PRD 7 - Authentication).

SIWAK punya dua pintu masuk:

  * SSO UI CAS — untuk mentee dan mentor yang punya akun SSO aktif. Seluruh
    alurnya ada di `siwak/sso.py` dan tidak disentuh dari sini.
  * Akun Khusus — username dan password, untuk tiga jenis akun yang tidak
    lewat SSO UI:
      - mentor non-SSO, dibuat pengelola di panel (`MentorLokalForm`);
      - pengurus SIWAK (`is_staff`) dan superuser;
      - akun pemindai QR (gatekeeper, divisi konsumsi), dibuat pengelola di
        panel (`AkunPemindaiForm`). Akun ini bukan staf, jadi login admin
        Django menolaknya — pintu inilah jalan masuknya.

`login_pilihan` adalah halaman yang mempertemukan keduanya, dan itulah yang
dipakai `LOGIN_URL` supaya akun non-SSO tidak langsung dilempar ke CAS.
Setelah masuk, tujuannya ditentukan `role_landing_url` untuk kedua pintu.
"""

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render, resolve_url
from django.urls import reverse

from .models import Profile, SiwakInfo
from .services.pemindai import boleh_memindai
from .sso import role_landing_url
from .utils import next_aman


def login_pilihan(request):
    """Halaman pemilih metode login: SSO UI atau Akun Khusus.

    `next` diteruskan ke kedua tautan — tanpa itu deep link yang membawa orang
    ke sini lewat @login_required hilang begitu dia memilih metodenya.
    """
    if request.user.is_authenticated:
        return redirect(next_aman(request) or role_landing_url(request.user))

    return render(request, "siwak/auth/login_pilihan.html", {
        "next": next_aman(request),
        "url_sso": reverse("siwak:cas_ng_login"),
        "url_khusus": reverse("siwak:login_khusus"),
        # Link CP-nya diatur pengelola lewat panel (SiwakInfo.kontak_cp), sama
        # dengan yang dipakai halaman "Cari Kelompok".
        "info": SiwakInfo.get_solo(),
    })


def boleh_masuk_akun_khusus(user):
    """Apakah `user` termasuk akun yang memang masuk lewat pintu Akun Khusus.

    Yang tidak termasuk justru yang punya pintunya sendiri: mentee dan mentor
    ber-SSO masuk lewat SSO UI. Superuser lolos lewat `boleh_memindai()` walau
    `is_staff`-nya mati.
    """
    return (
        user.is_staff
        or boleh_memindai(user)
        or Profile.objects.filter(
            user=user,
            role=Profile.ROLE_MENTOR,
            auth_source=Profile.SOURCE_LOKAL,
        ).exists()
    )


class AkunKhususLoginForm(AuthenticationForm):
    """Form login lokal, dibatasi untuk mentor non-SSO, pengurus, dan pemindai QR.

    Tanpa pembatasan ini setiap `User` berpassword valid bisa memakai halaman
    ini. `ModelBackend` yang mengautentikasi (CASBackend bersignature
    `(request, ticket, service)` sehingga `authenticate()` melewatinya untuk
    kredensial username/password), jadi penyaringnya harus di lapisan form.
    Penolakannya memakai galat "username/password salah" yang sama, supaya
    halaman ini tidak bisa dipakai menebak akun mana yang ada.
    """

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not boleh_masuk_akun_khusus(user):
            raise self.get_invalid_login_error()


class AkunKhususLoginView(LoginView):
    """LoginView biasa dengan form terbatas dan tujuan yang sadar role."""

    template_name = "siwak/auth/login_khusus.html"
    authentication_form = AkunKhususLoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        # `role_landing_url` sudah dipakai jalur SSO; jangan tulis ulang aturan
        # tujuan per role di dua tempat. `next` eksplisit tetap menang, supaya
        # pemindai yang login karena memindai QR kembali ke QR itu.
        return next_aman(self.request) or role_landing_url(self.request.user)


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
