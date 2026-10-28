from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

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


def _state(request, state, info=None, status=200, rejected=False):
    if request.method == "POST" and "application/json" in request.headers.get("Accept", ""):
        if rejected:
            message = "Pendaftaran belum dibuka." if state == "belum_dibuka" else "Pendaftaran sudah ditutup."
            return JsonResponse({"message": message + " Isian tidak disimpan."}, status=status)
        return JsonResponse({"redirect": reverse("amfm:daftar")}, status=status)
    return render(request, "amfm/status.html", {"state": state, "info": info, "rejected": rejected}, status=status)


def _kembali_daftar(request):
    url = reverse("amfm:daftar") + "?terkirim=1"
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"redirect": url})
    return redirect(url)


def _form_response(request, info, form, existing=None):
    step = 1 if any(name in form.errors for name in ("jenis_kelamin", "kontak")) else 2
    if request.method == "POST" and "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"errors": form.errors.get_json_data(), "step": step}, status=400)
    # Form yang gagal validasi dapat mengubah instance di memori; tampilkan berkas yang masih tersimpan.
    saved = Pendaftaran.objects.filter(pk=existing.pk).first() if existing else None
    return render(request, "amfm/daftar.html", {
        "info": info, "form": form, "step": step if form.is_bound else 1,
        "is_edit": bool(existing),
        "existing_files": [
            {"name": f"Bukti follow Instagram {number}", "url": reverse("amfm:bukti_peserta", args=[number])}
            if saved and getattr(saved, name) else None
            for number, name in enumerate(("bukti_follow", "bukti_follow_2"), 1)
        ],
        "portfolio_ids": [str(b.pk) for b in form.fields["pilihan_1"].queryset if form.portfolio_birdept(b)],
    })


def _hapus_file_baru(pendaftaran, old_names):
    if pendaftaran:
        for file in (pendaftaran.bukti_follow, pendaftaran.bukti_follow_2):
            if file.name and file.name not in old_names and file._committed:
                file.delete(save=False)


@never_cache
@sso_required
@require_http_methods(["GET", "POST"])
def daftar(request):
    info = AmfmInfo.get_solo()
    existing = Pendaftaran.objects.filter(user=request.user).first()
    if request.method == "GET":
        if existing and (info.status_saat_ini != "dibuka" or request.GET.get("terkirim") == "1"):
            return _state(request, "terkirim", info)
        if info.status_saat_ini != "dibuka":
            return _state(request, info.status_saat_ini, info)
        profile = Profile.objects.filter(user=request.user).first()
        if not identitas_valid(request, profile):
            return _state(request, "identitas_tidak_lengkap", status=403)
        if Pendaftaran.objects.filter(npm=profile.npm).exclude(user=request.user).exists():
            return _state(request, "sudah_terdaftar", status=409)
        return _form_response(request, info, PendaftaranForm(profile=profile, instance=existing), existing)

    pendaftaran = None
    profile = None
    old_files = []
    try:
        with transaction.atomic():
            # Kunci pengaturan lebih dulu agar perubahan deadline dan pengiriman terserialkan.
            info = AmfmInfo.objects.select_for_update().get(pk=info.pk)
            if info.status_saat_ini != "dibuka":
                return _state(request, info.status_saat_ini, info, status=409, rejected=True)
            profile = Profile.objects.select_for_update().filter(user=request.user).first()
            if not identitas_valid(request, profile):
                return _state(request, "identitas_tidak_lengkap", status=403)
            existing = Pendaftaran.objects.select_for_update().filter(user=request.user).first()
            if Pendaftaran.objects.filter(npm=profile.npm).exclude(user=request.user).exists():
                return _state(request, "sudah_terdaftar", status=409)
            old_files = (
                [(file.storage, file.name) for file in (existing.bukti_follow, existing.bukti_follow_2) if file.name]
                if existing else []
            )
            form = PendaftaranForm(request.POST, request.FILES, profile=profile, instance=existing)
            if not form.is_valid():
                return _form_response(request, info, form, existing)
            old_names = {name for _, name in old_files}
            pendaftaran = form.save(commit=False)
            pendaftaran.user = request.user
            pendaftaran.npm = profile.npm
            pendaftaran.nama_lengkap = profile.nama_lengkap
            pendaftaran.jurusan = profile.jurusan
            if (existing and existing.penempatan_id
                    and existing.penempatan_id not in (pendaftaran.pilihan_1_id, pendaftaran.pilihan_2_id)):
                pendaftaran.penempatan = None
                pendaftaran.status = "menunggu"
            pendaftaran.save()
            # Upload storage dapat melewati deadline; batalkan data dan hanya hapus berkas baru.
            if info.status_saat_ini != "dibuka":
                _hapus_file_baru(pendaftaran, old_names)
                transaction.set_rollback(True)
                return _state(request, info.status_saat_ini, info, status=409, rejected=True)
            current_names = {file.name for file in (pendaftaran.bukti_follow, pendaftaran.bukti_follow_2) if file.name}
            for storage, name in old_files:
                if name not in current_names:
                    transaction.on_commit(lambda storage=storage, name=name: storage.delete(name))
    except Exception as error:
        # Storage tidak ikut rollback transaksi database; berkas lama tetap milik record sebelumnya.
        _hapus_file_baru(pendaftaran, {name for _, name in old_files})
        if (isinstance(error, IntegrityError) and profile
                and Pendaftaran.objects.filter(Q(user=request.user) | Q(npm=profile.npm)).exists()):
            return redirect("amfm:daftar")
        raise
    return _kembali_daftar(request)


@never_cache
@sso_required
@require_GET
def bukti_peserta(request, nomor):
    if nomor not in (1, 2):
        raise Http404
    pendaftaran = Pendaftaran.objects.filter(user=request.user).first()
    file = getattr(pendaftaran, "bukti_follow" if nomor == 1 else "bukti_follow_2", None)
    if not file:
        raise Http404
    try:
        filename = f"bukti-follow-{nomor}" + (".png" if file.name.endswith(".png") else ".jpg")
        response = FileResponse(file.open("rb"), filename=filename)
    except FileNotFoundError:
        raise Http404 from None
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@never_cache
@require_POST
def masuk_sso(request):
    """Pilihan eksplisit pengguna: ganti sesi lokal / segarkan atribut CAS.

    Tidak membuat pintu autentikasi baru: logout Django lalu kembali ke view
    CAS yang sama. Sesi universitas tetap bisa dipakai tanpa mengisi sandi lagi.
    """
    logout(request)
    return redirect_to_login(reverse("amfm:daftar"), reverse("siwak:cas_ng_login"))
