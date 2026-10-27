from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.db import IntegrityError, transaction
from django.db.models import Q
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


@never_cache
@sso_required
@require_http_methods(["GET", "POST"])
def daftar(request):
    info = AmfmInfo.get_solo()
    # Sukses tetap terlihat setelah deadline. Tidak menampilkan jawaban peserta.
    if Pendaftaran.objects.filter(user=request.user).exists():
        return render(request, "amfm/status.html", {"state": "terkirim", "info": info})
    if info.status_saat_ini != "dibuka":
        return render(request, "amfm/status.html", {"state": info.status_saat_ini, "info": info})
    profile = Profile.objects.filter(user=request.user).first()
    if not identitas_valid(request, profile):
        return render(request, "amfm/status.html", {"state": "identitas_tidak_lengkap"}, status=403)
    if Pendaftaran.objects.filter(npm=profile.npm).exists():
        return render(request, "amfm/status.html", {"state": "sudah_terdaftar"}, status=409)

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
                    return render(request, "amfm/status.html", {"state": "identitas_tidak_lengkap"}, status=403)
                if Pendaftaran.objects.filter(Q(user=request.user) | Q(npm=profile.npm)).exists():
                    return redirect("amfm:daftar")
                if info.status_saat_ini != "dibuka":
                    return render(request, "amfm/status.html", {"state": info.status_saat_ini, "info": info}, status=409)
                pendaftaran = form.save(commit=False)
                pendaftaran.user = request.user
                pendaftaran.npm = profile.npm
                pendaftaran.nama_lengkap = profile.nama_lengkap
                pendaftaran.jurusan = profile.jurusan
                pendaftaran.save()
                # Upload storage dapat melewati deadline meskipun form valid.
                if info.status_saat_ini != "dibuka":
                    pendaftaran.bukti_follow.delete(save=False)
                    transaction.set_rollback(True)
                    return render(request, "amfm/status.html", {"state": info.status_saat_ini, "info": info}, status=409)
        except Exception as error:
            # Storage tidak ikut rollback transaksi database.
            if pendaftaran and pendaftaran.bukti_follow._committed:
                pendaftaran.bukti_follow.delete(save=False)
            if isinstance(error, IntegrityError) and Pendaftaran.objects.filter(
                Q(user=request.user) | Q(npm=profile.npm)
            ).exists():
                return redirect("amfm:daftar")
            raise
        return redirect("amfm:daftar")
    step = 1 if any(name in form.errors for name in ("jenis_kelamin", "kontak")) else 2
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
