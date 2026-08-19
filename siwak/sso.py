"""Authentication helper for the SIWAK section (PRD 7 - Authentication).

PRD 7 says login is "Menggunakan SSO UI" (Universitas Indonesia's central CAS
SSO at https://sso.ui.ac.id/cas2/). Wiring up the *real* SSO UI requires two
things this environment cannot provide on its own:

  1. The FUKI website registered as an official "service" with UI's SSO/PPSI
     team (they whitelist the callback URL).
  2. A CAS client library talking to that server (e.g. `django-cas-ng`).

So this module implements the same shape a real CAS login would have — a
"login" entrypoint that resolves to a Django `User` + `MabaProfile`, after
which every other authorized feature (tugas, RSVP, QR) works identically —
but the entrypoint itself is a simple NPM + Nama + Jurusan form instead of a
redirect to sso.ui.ac.id. That keeps the swap to real SSO a small, isolated
change instead of a rewrite. See the bottom of this file for that swap.
"""

from django.contrib.auth import get_user_model, login as django_login

from .models import MabaProfile

User = get_user_model()


def login_or_create_maba(request, npm: str, nama_lengkap: str, jurusan: str, angkatan: str = "") -> MabaProfile:
    """Dev-mode stand-in for a successful SSO UI assertion.

    Given the identity attributes SSO UI would normally assert about the
    user (NPM, nama, jurusan), get-or-create the matching Django User +
    MabaProfile and log them in. Idempotent: logging in twice with the same
    NPM reuses the same account instead of duplicating it.
    """
    user, _created = User.objects.get_or_create(
        username=npm,
        defaults={"first_name": nama_lengkap[:150]},
    )
    profile, _ = MabaProfile.objects.update_or_create(
        user=user,
        defaults={
            "npm": npm,
            "nama_lengkap": nama_lengkap,
            "jurusan": jurusan,
            "angkatan": angkatan,
        },
    )
    django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    # Link any pre-imported PesertaMentoring row (from the admin's kelompok
    # upload) to this account, matched by NPM, so Tugas/RSVP can find their
    # kelompok without asking them to search again.
    from .models import PesertaMentoring  # local import: avoids a circular import at module load

    PesertaMentoring.objects.filter(npm=npm, user__isnull=True).update(user=user)
    return profile


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