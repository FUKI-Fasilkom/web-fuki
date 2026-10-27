"""Panel AMFM: kerangka Figma, deklarasi dan helper dari mesin panel situs."""
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from urllib.parse import urlencode
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from birdep.models import BirDep
from main.panel import PER_HALAMAN, sel_baris
from siwak.akses import AksesDitolak
from siwak.models import JURUSAN_CHOICES
from siwak.utils import cari_teks, kueri_tanpa_halaman, next_aman
from .akses import amfm_required, boleh_kelola_amfm
from .models import AmfmInfo, Pendaftaran
from .panel import KONTEN, PENDAFTAR
from .panel_forms import KeputusanForm, KontenForm, PengaturanForm, StatusMassalForm
from .services.seleksi import STATUS, simpan_keputusan, ubah_status_massal
from .services.statistik import statistik_panel


class LoginAdminForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not boleh_kelola_amfm(user):
            raise self.get_invalid_login_error()


@method_decorator(never_cache, name="dispatch")
class LoginAdminView(LoginView):
    template_name = "amfm/panel/login.html"
    authentication_form = LoginAdminForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not boleh_kelola_amfm(request.user):
            raise AksesDitolak("amfm")
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return next_aman(self.request) or reverse("amfm:panel_beranda")


def _konteks(request, judul, aktif="pendaftar", **extra):
    konteks = {
        "judul_panel": judul, "tab_aktif": aktif,
        "boleh_ubah": request.user.has_perm("amfm.change_pendaftaran"),
        "boleh_hapus": request.user.has_perm("amfm.delete_pendaftaran"),
        "boleh_pengaturan": request.user.has_perm("amfm.change_amfminfo"),
        "boleh_konten": any(request.user.has_perm(f"amfm.{aksi}_{model}") for model in ("amfminfo", "amfmbenefit", "amfmtimeline") for aksi in ("view", "change", "add", "delete")),
    }
    model_konten = [(slug, sumber) for slug, sumber in KONTEN.items()
                    if request.user.has_perm(f"amfm.view_{sumber.model._meta.model_name}")
                    or request.user.has_perm(f"amfm.change_{sumber.model._meta.model_name}")]
    konteks["menu_konten"] = [{"label": sumber.label_jamak, "url": reverse("amfm:panel_konten_daftar", args=[slug])} for slug, sumber in model_konten]
    konteks["url_konten"] = reverse("amfm:panel_konten") if konteks["boleh_pengaturan"] else (konteks["menu_konten"][0]["url"] if model_konten else "")
    konteks.update(extra)
    return konteks


@amfm_required()
@require_GET
def panel_beranda(request):
    terbaru = PENDAFTAR.ambil_queryset()[:3]
    return render(request, "amfm/panel/dashboard.html", _konteks(
        request, "Dashboard", "dashboard", terbaru=terbaru, **statistik_panel(),
    ))


@amfm_required()
@require_GET
def panel_daftar(request):
    kata = (request.GET.get("q") or "").strip()
    qs = cari_teks(PENDAFTAR.ambil_queryset(), PENDAFTAR.pencarian, kata)
    birdept = list(BirDep.objects.all())
    pilihan_birdept = str(request.GET.get("birdept") or "")
    if pilihan_birdept in {str(b.pk) for b in birdept}:
        qs = qs.filter(Q(pilihan_1_id=pilihan_birdept) | Q(pilihan_2_id=pilihan_birdept))
    else:
        pilihan_birdept = ""
    status = request.GET.get("status", "")
    if status in STATUS:
        qs = qs.filter(status=status)
    else:
        status = ""
    halaman = Paginator(qs, PER_HALAMAN).get_page(request.GET.get("page"))
    for obj in halaman.object_list:
        obj.prodi_label = dict(JURUSAN_CHOICES).get(obj.jurusan, obj.jurusan)
    return render(request, "amfm/panel/daftar.html", _konteks(
        request, "List Pendaftar", halaman=halaman, kata=kata, birdept=birdept,
        pilihan_birdept=pilihan_birdept, status_terpilih=status, statuses=STATUS.items(),
        url_kembali=request.get_full_path(), kueri=kueri_tanpa_halaman(request),
    ))


def _obj(pk):
    return get_object_or_404(PENDAFTAR.ambil_queryset(), pk=pk)


def _detail(request, obj, form=None, status=200):
    return render(request, "amfm/panel/detail.html", _konteks(
        request, "List Pendaftar › Detail Pendaftar", obj=obj,
        form=form if form is not None else KeputusanForm(instance=obj),
        prodi=dict(JURUSAN_CHOICES).get(obj.jurusan, obj.jurusan),
        url_kembali=next_aman(request) or reverse("amfm:panel_daftar"),
    ), status=status)


@amfm_required()
@require_GET
def panel_detail(request, pk):
    return _detail(request, _obj(pk))


@amfm_required("amfm.change_pendaftaran")
@require_POST
def panel_keputusan(request, pk):
    obj = _obj(pk)
    form = KeputusanForm(request.POST, instance=obj)
    if form.is_valid():
        try:
            simpan_keputusan(pk, form.cleaned_data["status"], getattr(form.cleaned_data["penempatan"], "pk", None))
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Keputusan penerimaan berhasil disimpan.")
            url = reverse("amfm:panel_detail", args=[pk])
            return redirect(f"{url}?{urlencode({'next': next_aman(request)})}" if next_aman(request) else url)
    # ModelForm mengubah instance saat validasi; badge tetap membaca data tersimpan.
    obj.refresh_from_db()
    return _detail(request, obj, form, status=400)


@amfm_required("amfm.change_pendaftaran")
@require_POST
def panel_massal(request):
    form = StatusMassalForm(request.POST)
    if form.is_valid():
        try:
            jumlah = ubah_status_massal(form.cleaned_data["ids"].values_list("pk", flat=True), form.cleaned_data["status"], getattr(form.cleaned_data["penempatan"], "pk", None))
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"Status {jumlah} pendaftar berhasil diperbarui.")
    else:
        messages.error(request, "Pilih pendaftar, status yang valid, dan centang konfirmasi perubahan.")
    return redirect(next_aman(request) or reverse("amfm:panel_daftar"))


@amfm_required("amfm.delete_pendaftaran")
@require_http_methods(["GET", "POST"])
def panel_hapus(request, pk):
    obj = _obj(pk)
    if request.method == "POST" and request.POST.get("konfirmasi") == "ya":
        with transaction.atomic():
            obj = get_object_or_404(Pendaftaran.objects.select_for_update(), pk=pk)
            obj.delete()
        messages.success(request, "Data pendaftar berhasil dihapus.")
        return redirect(next_aman(request) or reverse("amfm:panel_daftar"))
    return render(request, "amfm/panel/hapus.html", _konteks(
        request, "Hapus Pendaftar", obj=obj, url_kembali=next_aman(request) or reverse("amfm:panel_detail", args=[pk]),
    ))


@amfm_required()
@require_GET
def panel_bukti(request, pk):
    obj = _obj(pk)
    if not obj.bukti_follow:
        raise Http404
    try:
        file = obj.bukti_follow.open("rb")
    except FileNotFoundError:
        raise Http404 from None
    response = FileResponse(file, as_attachment=True, filename="bukti-follow" + (".png" if obj.bukti_follow.name.endswith(".png") else ".jpg"))
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@amfm_required("amfm.change_amfminfo")
@require_http_methods(["GET", "POST"])
def panel_pengaturan(request):
    # Kunci yang sama dengan view daftar: perubahan status/deadline tidak
    # menyela transaksi pengiriman peserta yang sedang berlangsung.
    with transaction.atomic():
        info = AmfmInfo.get_solo()
        if request.method == "POST":
            info = AmfmInfo.objects.select_for_update().get(pk=info.pk)
        form = PengaturanForm(request.POST if request.method == "POST" else None, instance=info)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, "Pengaturan pendaftaran berhasil disimpan.")
            return redirect("amfm:panel_pengaturan")
    return render(request, "amfm/panel/form.html", _konteks(
        request, "Pengaturan Pendaftaran", "pengaturan", form=form,
        deskripsi="Atur jadwal, guidebook, dan folder kurikulum. Perubahan langsung berlaku pada formulir peserta.",
        status_saat_ini=info.status_saat_ini,
    ))


def _izin_konten(request, model, aksi):
    if not request.user.has_perm(f"amfm.{aksi}_{model._meta.model_name}"):
        raise AksesDitolak("amfm")


@amfm_required()
@require_http_methods(["GET", "POST"])
def panel_konten(request):
    _izin_konten(request, AmfmInfo, "change")
    with transaction.atomic():
        info = AmfmInfo.get_solo()
        if request.method == "POST":
            info = AmfmInfo.objects.select_for_update().get(pk=info.pk)
        form = KontenForm(request.POST if request.method == "POST" else None, request.FILES or None, instance=info)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, "Konten halaman AM-FM berhasil diperbarui.")
            return redirect("amfm:panel_konten")
    return render(request, "amfm/panel/form.html", _konteks(request, "Konten Halaman AM-FM", "konten", form=form))


def _sumber(slug):
    if slug not in KONTEN:
        raise Http404
    return KONTEN[slug]


@amfm_required()
@require_GET
def panel_konten_daftar(request, slug):
    sumber = _sumber(slug)
    if not (request.user.has_perm(f"amfm.view_{sumber.model._meta.model_name}") or request.user.has_perm(f"amfm.change_{sumber.model._meta.model_name}")):
        raise AksesDitolak("amfm")
    halaman = Paginator(sumber.ambil_queryset().order_by("urutan", "pk") if slug == "benefit" else sumber.ambil_queryset().order_by("tanggal_mulai", "pk"), PER_HALAMAN).get_page(request.GET.get("page"))
    model = sumber.model._meta.model_name
    return render(request, "amfm/panel/konten_daftar.html", _konteks(
        request, sumber.label_jamak, "konten", sumber=sumber,
        halaman=halaman, baris=[{"obj": obj, "sel": sel_baris(obj, sumber, n)} for n, obj in enumerate(halaman.object_list, start=halaman.start_index())],
        tambah=request.user.has_perm(f"amfm.add_{model}"), ubah=request.user.has_perm(f"amfm.change_{model}"), hapus=request.user.has_perm(f"amfm.delete_{model}"),
    ))


@amfm_required()
@require_http_methods(["GET", "POST"])
def panel_konten_form(request, slug, pk=None):
    sumber = _sumber(slug)
    _izin_konten(request, sumber.model, "change" if pk else "add")
    obj = get_object_or_404(sumber.model, pk=pk) if pk else None
    form = sumber.form(request.POST if request.method == "POST" else None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{sumber.label} berhasil disimpan.")
        return redirect("amfm:panel_konten_daftar", slug=slug)
    return render(request, "amfm/panel/form.html", _konteks(request, f"{'Ubah' if pk else 'Tambah'} {sumber.label}", "konten", form=form))


@amfm_required()
@require_http_methods(["GET", "POST"])
def panel_konten_hapus(request, slug, pk):
    sumber = _sumber(slug)
    _izin_konten(request, sumber.model, "delete")
    obj = get_object_or_404(sumber.model, pk=pk)
    url = reverse("amfm:panel_konten_daftar", args=[slug])
    if request.method == "POST" and request.POST.get("konfirmasi") == "ya":
        obj.delete()
        messages.success(request, f"{sumber.label} berhasil dihapus.")
        return redirect(url)
    return render(request, "amfm/panel/hapus.html", _konteks(request, f"Hapus {sumber.label}", "konten", obj=obj, url_kembali=url))
