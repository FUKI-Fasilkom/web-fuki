from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from siwak.models import Profile

from .akses import identitas_valid, sso_required
from .forms import PendaftaranForm
from .models import AmfmBenefit, AmfmInfo, AmfmTimeline, Pendaftaran


def beranda(request):
    """Halaman informasi tetap publik, termasuk ketika pendaftaran ditutup."""
    context = {
        "info": AmfmInfo.get_solo(),
        "benefit_list": AmfmBenefit.objects.all(),
        "timeline_list": AmfmTimeline.objects.filter(is_active=True),
        "url_daftar": reverse("amfm:daftar"),
    }
    return render(request, "amfm/beranda.html", context)


def _state(request, state, info=None, status=200):
    if request.method == "POST" and "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"redirect": reverse("amfm:daftar")}, status=status)
    return render(request, "amfm/status.html", {"state": state, "info": info}, status=status)


def _kembali_daftar(request):
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"redirect": reverse("amfm:daftar")})
    return redirect("amfm:daftar")


@never_cache
@sso_required
@require_http_methods(["GET", "POST"])
def daftar(request):
    info = AmfmInfo.get_solo()
    # Sukses tetap terlihat setelah deadline. Tidak menampilkan jawaban peserta.
    if Pendaftaran.objects.filter(user=request.user).exists():
        return _state(request, "terkirim", info)
    if info.status_saat_ini != "dibuka":
        return _state(request, info.status_saat_ini, info)
    profile = Profile.objects.filter(user=request.user).first()
    if not identitas_valid(request, profile):
        return _state(request, "identitas_tidak_lengkap", status=403)
    if Pendaftaran.objects.filter(npm=profile.npm).exists():
        return _state(request, "sudah_terdaftar", status=409)

    form = PendaftaranForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None, profile=profile,
    )
    if request.method == "POST" and form.is_valid():
        pendaftaran = None
        try:
            with transaction.atomic():
                # Urutan kunci sama untuk semua pengiriman. Perubahan pengaturan
                # admin ikut terserialkan; dua klik Kirim tidak menyimpan dua file.
                info = AmfmInfo.objects.select_for_update().get(pk=info.pk)
                profile = Profile.objects.select_for_update().get(pk=profile.pk)
                if not identitas_valid(request, profile):
                    return _state(request, "identitas_tidak_lengkap", status=403)
                if Pendaftaran.objects.filter(Q(user=request.user) | Q(npm=profile.npm)).exists():
                    return _kembali_daftar(request)
                if info.status_saat_ini != "dibuka":
                    return _state(request, info.status_saat_ini, info, status=409)
                pendaftaran = form.save(commit=False)
                pendaftaran.user = request.user
                pendaftaran.npm = profile.npm
                pendaftaran.nama_lengkap = profile.nama_lengkap
                pendaftaran.jurusan = profile.jurusan
                pendaftaran.save()
                # Upload storage dapat melewati deadline meskipun form valid.
                if info.status_saat_ini != "dibuka":
                    for file in (pendaftaran.bukti_follow, pendaftaran.bukti_follow_2):
                        if file.name:
                            file.delete(save=False)
                    transaction.set_rollback(True)
                    return _state(request, info.status_saat_ini, info, status=409)
        except Exception as error:
            # Storage tidak ikut rollback transaksi database.
            if pendaftaran:
                for file in (pendaftaran.bukti_follow, pendaftaran.bukti_follow_2):
                    if file.name and file._committed:
                        file.delete(save=False)
            if isinstance(error, IntegrityError) and Pendaftaran.objects.filter(
                Q(user=request.user) | Q(npm=profile.npm)
            ).exists():
                return _kembali_daftar(request)
            raise
        return _kembali_daftar(request)
    step = 1 if any(name in form.errors for name in ("jenis_kelamin", "kontak")) else 2
    if request.method == "POST" and "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"errors": form.errors.get_json_data(), "step": step}, status=400)
    return render(request, "amfm/daftar.html", {
        "info": info, "form": form, "step": step if form.is_bound else 1,
        "portfolio_ids": [str(b.pk) for b in form.fields["pilihan_1"].queryset if form.portfolio_birdept(b)],
    })


@never_cache
@require_POST
def masuk_sso(request):
    """Pilihan eksplisit pengguna: ganti sesi lokal / segarkan atribut CAS.

    Tidak membuat pintu autentikasi baru: logout Django lalu kembali ke view
    CAS yang sama. Sesi universitas tetap bisa dipakai tanpa mengisi sandi lagi.
    """
    logout(request)
    return redirect_to_login(reverse("amfm:daftar"), reverse("siwak:cas_ng_login"))
