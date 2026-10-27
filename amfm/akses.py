"""AM-FM memakai sesi CAS dan profil yang sudah disinkronkan SIWAK."""
from functools import wraps

from django.contrib.auth import BACKEND_SESSION_KEY
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render
from django.urls import reverse

from siwak.models import Profile
from siwak.sso import KD_ORG_PROGRAM_MAP, get_attribute


def sso_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("siwak:cas_ng_login"))
        if request.session.get(BACKEND_SESSION_KEY) != "django_cas_ng.backends.CASBackend":
            return render(request, "amfm/status.html", {"state": "perlu_sso"}, status=403)
        return view(request, *args, **kwargs)
    return wrapped


def identitas_valid(request, profile):
    attributes = request.session.get("attributes") or {}
    if not isinstance(attributes, dict) or not profile or profile.auth_source != Profile.SOURCE_SSO:
        return False
    try:
        npm = get_attribute(attributes, "npm")
        nama = get_attribute(attributes, "nama")
        kode = get_attribute(attributes, "kd_org").split(".")[0]
    except (AttributeError, TypeError):
        return False
    return bool(
        npm and npm.isascii() and npm.isdigit() and nama and nama != "None"
        and profile.npm == npm and profile.nama_lengkap == nama
        and profile.jurusan and profile.jurusan == KD_ORG_PROGRAM_MAP.get(kode)
    )
