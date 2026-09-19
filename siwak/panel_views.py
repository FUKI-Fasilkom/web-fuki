"""View panel pengelola SIWAK (/siwak/admin/).

Empat view CRUD di bawah (`panel_daftar`, `panel_tambah`, `panel_ubah`,
`panel_hapus`) melayani *semua* jenis data yang terdaftar di `panel.py`. Yang
membedakan satu menu dengan menu lain hanyalah isi `Sumber`-nya, bukan kodenya.

Di luar itu ada dua kelompok view kecil: halaman khusus yang memang tidak
berbentuk CRUD biasa (konten halaman utama dan daftar RSVP per acara), dan
penyunting relasi (`panel_set_kelompok`, `panel_set_mentor`) yang dipanggil
langsung dari dropdown di halaman daftar tanpa membuka form ubah.
"""

import csv
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Max, ProtectedError, Q
from django.forms import inlineformset_factory
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import (
    Choice,
    EventRSVP,
    KelompokMentoring,
    MabaProfile,
    Mentor,
    MentoringSession,
    PesertaMentoring,
    Question,
    SiwakEvent,
    SiwakInfo,
    Tugas,
)
from .panel import (
    BAGIAN,
    HALAMAN_KHUSUS,
    PETA_BAGIAN,
    PETA_SUMBER,
    daftar_kelompok,
    daftar_mentor,
    sumber_bagian,
)
from .panel_forms import InfoSiwakForm, PertanyaanForm, PilihanForm

PER_HALAMAN = 25

# Tipe kolom yang isinya dropdown penyunting relasi, bukan sekadar tulisan.
# Dipakai untuk menentukan daftar pilihan apa yang perlu ikut dikirim ke templat.
TIPE_BUTUH_KELOMPOK = {"pilih_kelompok", "pilih_kelompok_mentor"}
TIPE_BUTUH_MENTOR = {"atur_mentor"}


def staf_required(view_func):
    """Hanya untuk pengurus. Mengikuti pola `superuser_required` di views.py:
    yang belum login diarahkan ke login admin, yang sudah login tapi bukan staf
    mendapat 403 — bukan dilempar balik ke halaman login berulang-ulang."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated:
            if not request.user.is_staff:
                return HttpResponseForbidden(
                    "Akun ini tidak punya akses ke panel SIWAK."
                )
            return view_func(request, *args, **kwargs)
        return redirect_to_login(request.get_full_path(), reverse("admin:login"))

    return _wrapped


# ---------------------------------------------------------------------------
# Kerangka bersama
# ---------------------------------------------------------------------------

def _menu(bagian_aktif="", sumber_aktif="", khusus_aktif=""):
    """Susun menu samping dari peta di panel.py supaya tidak ada daftar menu
    kedua yang harus ikut diubah setiap kali ada jenis data baru."""
    menu = []
    for bagian in BAGIAN:
        butir = []
        for nama_url, label, _ in HALAMAN_KHUSUS.get(bagian.slug, []):
            butir.append({
                "label": label,
                "url": reverse(f"siwak:{nama_url}"),
                "aktif": khusus_aktif == nama_url,
                "sorot": True,
            })
        for sumber in sumber_bagian(bagian.slug):
            butir.append({
                "label": sumber.label_jamak,
                "url": reverse("siwak:panel_daftar", args=[sumber.slug]),
                "aktif": sumber_aktif == sumber.slug,
                "sorot": False,
            })
        menu.append({
            "bagian": bagian,
            "butir": butir,
            "aktif": bagian_aktif == bagian.slug,
        })
    return menu


def _kerangka(request, *, judul, bagian="", sumber="", khusus="", remah=(), **ekstra):
    konteks = {
        "judul_panel": judul,
        "menu": _menu(bagian, sumber, khusus),
        "remah": list(remah),
        "bagian_aktif": bagian,
    }
    konteks.update(ekstra)
    return konteks


def _sumber_atau_404(slug):
    sumber = PETA_SUMBER.get(slug)
    if sumber is None:
        raise Http404("Jenis data tidak dikenal.")
    return sumber


# Kolom yang isinya penyunting kecil perlu tahu ke mana kiriman formnya pergi.
# Alamatnya bergantung pada baris, jadi dihitung di sini, bukan di templat.
URL_SEL = {
    "pilih_kelompok": "siwak:panel_set_kelompok",
    "pilih_kelompok_mentor": "siwak:panel_set_mentor_kelompok",
    "saklar_rsvp": "siwak:panel_rsvp_toggle",
    "pilih_aktif": "siwak:panel_sesi_aktif",
}


def _sel(obj, sumber):
    """Ubah satu objek jadi daftar sel siap render."""
    daftar = []
    for k in sumber.kolom:
        butir = {
            "judul": k.judul, "tipe": k.tipe, "nilai": k.ambil(obj),
            "utama": k.utama, "pk": obj.pk,
        }
        nama_url = URL_SEL.get(k.tipe)
        if nama_url:
            butir["url"] = reverse(nama_url, args=[obj.pk])
        daftar.append(butir)
    return daftar


def _aksi(obj, sumber):
    """Tombol tambahan baris ini — labelnya boleh menghitung isi objeknya."""
    return [
        {"label": a.label(obj), "url": reverse(a.nama_url, args=[obj.pk])}
        for a in sumber.aksi_baris
    ]


def _angka(nilai):
    """Pk dari isian form, atau None kalau kosong/bukan angka. Dipakai supaya
    pilihan dropdown yang kosong tidak pernah sampai ke query sebagai teks."""
    nilai = (nilai or "").strip()
    return int(nilai) if nilai.isdigit() else None


def _kembali(request, cadangan):
    """Kembali ke halaman daftar yang tadi dibuka — lengkap dengan pencarian,
    urutan, dan nomor halamannya — bukan ke halaman pertama."""
    tujuan = request.POST.get("next") or ""
    if tujuan and url_has_allowed_host_and_scheme(
        tujuan, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(tujuan)
    return redirect(cadangan)


# ---------------------------------------------------------------------------
# Pengurutan daftar
# ---------------------------------------------------------------------------

def _arah(ekspresi, turun):
    """Beri arah pada satu butir pengurutan. `nulls_last` dipakai di kedua arah
    supaya baris yang belum punya kelompok selalu jatuh di bawah, bukan
    menumpuk di baris teratas saat diurutkan menurun."""
    if isinstance(ekspresi, str):
        ekspresi = F(ekspresi)
    return ekspresi.desc(nulls_last=True) if turun else ekspresi.asc(nulls_last=True)


def _url_urut(request, kunci, turun):
    """Alamat daftar ini dengan urutan tertentu, tanpa kehilangan pencarian."""
    params = {
        k: v for k, v in request.GET.items()
        if k not in ("urut", "arah", "page") and v
    }
    params["urut"] = kunci
    if turun:
        params["arah"] = "turun"
    return f"?{urlencode(params)}"


def _urutkan(qs, sumber, request):
    """Terapkan urutan pilihan pengguna; kembalikan queryset + kunci + arahnya."""
    if not sumber.pengurutan:
        return qs, "", False

    kunci = request.GET.get("urut") or sumber.urut_awal
    if kunci not in sumber.pengurutan:
        kunci = sumber.urut_awal
    turun = request.GET.get("arah") == "turun"

    ekspresi = sumber.pengurutan.get(kunci)
    if not ekspresi:
        return qs, "", turun
    return qs.order_by(*[_arah(e, turun) for e in ekspresi]), kunci, turun


# ---------------------------------------------------------------------------
# Halaman depan & halaman bagian
# ---------------------------------------------------------------------------

@staf_required
def panel_beranda(request):
    kartu = []
    for bagian in BAGIAN:
        daftar = sumber_bagian(bagian.slug)
        kartu.append({
            "bagian": bagian,
            "url": reverse("siwak:panel_bagian", args=[bagian.slug]),
            "menu": [
                {"label": s.label_jamak, "jumlah": s.model.objects.count()}
                for s in daftar
            ],
        })

    ringkasan = [
        ("Peserta mentoring", MabaProfile.objects.count()),
        ("Kelompok mentoring", KelompokMentoring.objects.count()),
        ("Mentor", Mentor.objects.count()),
        ("Belum punya kelompok", PesertaMentoring.objects.filter(kelompok__isnull=True).count()),
    ]

    return render(request, "siwak/panel/beranda.html", _kerangka(
        request,
        judul="Panel Pengelola SIWAK-NG",
        kartu=kartu,
        ringkasan=ringkasan,
    ))


@staf_required
def panel_bagian(request, bagian):
    data = PETA_BAGIAN.get(bagian)
    if data is None:
        raise Http404("Bagian tidak dikenal.")

    butir = []
    for nama_url, label, keterangan in HALAMAN_KHUSUS.get(bagian, []):
        butir.append({
            "label": label,
            "deskripsi": keterangan,
            "url": reverse(f"siwak:{nama_url}"),
            "jumlah": None,
            "url_tambah": "",
        })
    for sumber in sumber_bagian(bagian):
        butir.append({
            "label": sumber.label_jamak,
            "deskripsi": sumber.deskripsi,
            "url": reverse("siwak:panel_daftar", args=[sumber.slug]),
            "jumlah": sumber.model.objects.count(),
            "url_tambah": (
                reverse("siwak:panel_tambah", args=[sumber.slug]) if sumber.boleh_tambah else ""
            ),
        })

    return render(request, "siwak/panel/bagian.html", _kerangka(
        request,
        judul=data.nama,
        bagian=bagian,
        remah=[(data.nama, "")],
        data_bagian=data,
        butir=butir,
    ))


# ---------------------------------------------------------------------------
# CRUD generik
# ---------------------------------------------------------------------------

@staf_required
def panel_daftar(request, slug):
    sumber = _sumber_atau_404(slug)
    bagian = PETA_BAGIAN[sumber.bagian]

    qs = sumber.ambil_queryset()
    kata = (request.GET.get("q") or "").strip()
    if kata and sumber.pencarian:
        filter_cari = Q()
        for nama_field in sumber.pencarian:
            filter_cari |= Q(**{f"{nama_field}__icontains": kata})
        qs = qs.filter(filter_cari)

    qs, kunci_urut, turun = _urutkan(qs, sumber, request)

    halaman = Paginator(qs, PER_HALAMAN).get_page(request.GET.get("page"))
    baris = [
        {"obj": o, "pk": o.pk, "sel": _sel(o, sumber), "aksi": _aksi(o, sumber)}
        for o in halaman.object_list
    ]

    # Judul kolom yang bisa diklik untuk mengurutkan. Sekali klik = menaik,
    # klik lagi pada kolom yang sama = menurun.
    kepala = []
    for kolom in sumber.kolom:
        aktif = bool(kolom.urut) and kolom.urut == kunci_urut
        kepala.append({
            "judul": kolom.judul,
            "bisa_urut": bool(kolom.urut),
            "aktif": aktif,
            "turun": turun if aktif else False,
            "url": _url_urut(request, kolom.urut, (not turun) if aktif else False) if kolom.urut else "",
        })

    # Versi HP tidak punya judul kolom untuk diklik, jadi urutannya dipilih
    # lewat satu dropdown yang isinya sama persis.
    pilihan_urut = []
    for kolom in sumber.kolom_urut():
        for arah_turun, kata_arah in ((False, "A-Z"), (True, "Z-A")):
            pilihan_urut.append({
                "label": f"{kolom.judul} ({kata_arah})",
                "url": _url_urut(request, kolom.urut, arah_turun),
                "terpilih": kolom.urut == kunci_urut and arah_turun == turun,
            })

    tipe_kolom = {k.tipe for k in sumber.kolom}
    ekstra = {}
    if tipe_kolom & TIPE_BUTUH_KELOMPOK:
        ekstra["daftar_kelompok"] = daftar_kelompok()
    if tipe_kolom & TIPE_BUTUH_MENTOR:
        ekstra["daftar_mentor"] = daftar_mentor()

    return render(request, "siwak/panel/daftar.html", _kerangka(
        request,
        judul=sumber.label_jamak,
        bagian=sumber.bagian,
        sumber=sumber.slug,
        remah=[(bagian.nama, reverse("siwak:panel_bagian", args=[bagian.slug])), (sumber.label_jamak, "")],
        sumber_data=sumber,
        kepala=kepala,
        baris=baris,
        halaman=halaman,
        kata=kata,
        kunci_urut=kunci_urut,
        arah_turun=turun,
        pilihan_urut=pilihan_urut,
        # Dikirim ke setiap form dropdown supaya sesudah menyimpan, pengelola
        # kembali ke halaman, pencarian, dan urutan yang sama.
        url_kembali=request.get_full_path(),
        kueri=urlencode({k: v for k, v in request.GET.items() if k != "page" and v}),
        url_tambah=(
            reverse("siwak:panel_tambah", args=[sumber.slug]) if sumber.boleh_tambah else ""
        ),
        **ekstra,
    ))


def _simpan(request, sumber, instance=None):
    bagian = PETA_BAGIAN[sumber.bagian]
    ubah = instance is not None

    if request.method == "POST":
        form = sumber.form(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            obj = form.save()
            messages.success(
                request,
                f"{sumber.label} “{obj}” berhasil {'diperbarui' if ubah else 'ditambahkan'}.",
            )
            return redirect("siwak:panel_daftar", slug=sumber.slug)
        messages.error(request, "Masih ada isian yang perlu dibetulkan.")
    else:
        form = sumber.form(instance=instance)

    judul = f"Ubah {sumber.label}" if ubah else f"Tambah {sumber.label}"
    return render(request, "siwak/panel/form.html", _kerangka(
        request,
        judul=judul,
        bagian=sumber.bagian,
        sumber=sumber.slug,
        remah=[
            (bagian.nama, reverse("siwak:panel_bagian", args=[bagian.slug])),
            (sumber.label_jamak, reverse("siwak:panel_daftar", args=[sumber.slug])),
            (judul, ""),
        ],
        form=form,
        sumber_data=sumber,
        objek=instance,
        url_batal=reverse("siwak:panel_daftar", args=[sumber.slug]),
        url_hapus=(
            reverse("siwak:panel_hapus", args=[sumber.slug, instance.pk])
            if ubah and sumber.boleh_hapus
            else ""
        ),
    ))


@staf_required
def panel_tambah(request, slug):
    sumber = _sumber_atau_404(slug)
    if not sumber.boleh_tambah:
        raise Http404("Jenis data ini tidak bisa ditambah dari panel.")
    return _simpan(request, sumber)


@staf_required
def panel_ubah(request, slug, pk):
    sumber = _sumber_atau_404(slug)
    return _simpan(request, sumber, get_object_or_404(sumber.model, pk=pk))


@staf_required
@require_POST
def panel_hapus(request, slug, pk):
    sumber = _sumber_atau_404(slug)
    if not sumber.boleh_hapus:
        raise Http404("Jenis data ini tidak bisa dihapus dari panel.")
    objek = get_object_or_404(sumber.model, pk=pk)
    nama = str(objek)
    try:
        objek.delete()
    except ProtectedError:
        # Mis. aspek penilaian yang nilainya sudah dipakai mentor: lebih baik
        # bilang kenapa daripada melempar 500 ke pengurus.
        messages.error(
            request,
            f"{sumber.label} “{nama}” tidak bisa dihapus karena masih dipakai data lain.",
        )
        return redirect("siwak:panel_daftar", slug=sumber.slug)
    messages.success(request, f"{sumber.label} “{nama}” berhasil dihapus.")
    return redirect("siwak:panel_daftar", slug=sumber.slug)


# ---------------------------------------------------------------------------
# Penyunting relasi langsung dari daftar
# ---------------------------------------------------------------------------

@staf_required
@require_POST
def panel_set_kelompok(request, pk):
    """Pindahkan satu peserta ke kelompok lain langsung dari daftar peserta.

    `pk` adalah MabaProfile, karena itulah identitas yang ditampilkan daftar;
    baris PesertaMentoring-nya dibuat kalau memang belum ada, sehingga maba
    yang baru didaftarkan pengurus tetap bisa langsung ditempatkan.
    """
    maba = get_object_or_404(MabaProfile, pk=pk)
    cadangan = reverse("siwak:panel_daftar", args=["peserta"])

    pilihan = _angka(request.POST.get("kelompok"))
    kelompok = KelompokMentoring.objects.filter(pk=pilihan).first() if pilihan else None
    if pilihan and kelompok is None:
        messages.error(request, "Kelompok yang dipilih sudah tidak ada.")
        return _kembali(request, cadangan)

    peserta, _dibuat = PesertaMentoring.objects.get_or_create(maba=maba)
    if peserta.kelompok_id != (kelompok.pk if kelompok else None):
        peserta.kelompok = kelompok
        peserta.save(update_fields=["kelompok"])
        messages.success(
            request,
            f"{maba.nama_lengkap} dipindahkan ke {kelompok.nama_kelompok}." if kelompok
            else f"{maba.nama_lengkap} dikeluarkan dari kelompoknya.",
        )
    return _kembali(request, cadangan)


@staf_required
@require_POST
def panel_set_mentor(request):
    """Tambah atau lepas satu mentor dari satu kelompok, dari daftar Kelompok.

    Karena satu mentor hanya boleh memegang satu kelompok, menambahkan mentor
    yang sedang memegang kelompok lain berarti memindahkannya — dan pesannya
    memang menyebut itu, supaya kelompok yang ditinggalkan tidak kosong tanpa
    ada yang menyadari.
    """
    cadangan = reverse("siwak:panel_daftar", args=["kelompok"])

    kelompok = KelompokMentoring.objects.filter(pk=_angka(request.POST.get("kelompok"))).first()
    mentor = Mentor.objects.filter(pk=_angka(request.POST.get("mentor"))).first()
    if kelompok is None or mentor is None:
        messages.error(request, "Mentor atau kelompok yang dipilih sudah tidak ada.")
        return _kembali(request, cadangan)

    if request.POST.get("aksi") == "hapus":
        kelompok.mentor_list.remove(mentor)
        messages.success(request, f"{mentor.nama} dilepas dari {kelompok.nama_kelompok}.")
    else:
        sebelumnya = mentor.kelompok
        kelompok.mentor_list.add(mentor)
        if sebelumnya and sebelumnya.pk != kelompok.pk:
            messages.success(
                request,
                f"{mentor.nama} dipindahkan dari {sebelumnya.nama_kelompok} ke {kelompok.nama_kelompok}.",
            )
        else:
            messages.success(request, f"{mentor.nama} ditugaskan ke {kelompok.nama_kelompok}.")
    return _kembali(request, cadangan)


@staf_required
@require_POST
def panel_set_mentor_kelompok(request, pk):
    """Ganti kelompok yang dipegang satu mentor, dari daftar Mentor.

    Satu mentor satu kelompok, jadi kolomnya cukup satu dropdown: memilih
    kelompok lain memindahkannya, memilih pilihan kosong melepasnya.
    """
    mentor = get_object_or_404(Mentor, pk=pk)
    cadangan = reverse("siwak:panel_daftar", args=["mentor"])

    pilihan = _angka(request.POST.get("kelompok"))
    kelompok = KelompokMentoring.objects.filter(pk=pilihan).first() if pilihan else None
    if pilihan and kelompok is None:
        messages.error(request, "Kelompok yang dipilih sudah tidak ada.")
        return _kembali(request, cadangan)

    if mentor.kelompok_id != (kelompok.pk if kelompok else None):
        mentor.kelompok = kelompok
        mentor.save(update_fields=["kelompok"])
        messages.success(
            request,
            f"{mentor.nama} sekarang memegang {kelompok.nama_kelompok}." if kelompok
            else f"{mentor.nama} tidak lagi memegang kelompok.",
        )
    return _kembali(request, cadangan)


# ---------------------------------------------------------------------------
# Halaman khusus 1 — konten halaman utama (satu baris tetap)
# ---------------------------------------------------------------------------

@staf_required
def panel_info(request):
    info = SiwakInfo.get_solo()

    if request.method == "POST":
        form = InfoSiwakForm(request.POST, request.FILES, instance=info)
        if form.is_valid():
            form.save()
            messages.success(request, "Konten halaman utama SIWAK berhasil disimpan.")
            return redirect("siwak:panel_info")
        messages.error(request, "Masih ada isian yang perlu dibetulkan.")
    else:
        form = InfoSiwakForm(instance=info)

    bagian = PETA_BAGIAN["info"]
    return render(request, "siwak/panel/info.html", _kerangka(
        request,
        judul="Konten Halaman Utama",
        bagian="info",
        khusus="panel_info",
        remah=[(bagian.nama, reverse("siwak:panel_bagian", args=["info"])), ("Konten Halaman Utama", "")],
        form=form,
        info=info,
    ))


# ---------------------------------------------------------------------------
# Halaman khusus 2 — RSVP per acara
# ---------------------------------------------------------------------------

# Nama diambil dari profil maba, tapi peserta yang belum punya profil tetap
# harus bisa dicari, jadi username ikut dicocokkan.
CARI_RSVP = (
    "user__maba_profile__nama_lengkap",
    "user__maba_profile__npm",
    "user__username",
)


def _rsvp_queryset(event, kata=""):
    qs = (
        EventRSVP.objects.filter(event=event)
        .select_related("user__maba_profile")
        .order_by("user__maba_profile__nama_lengkap", "user__username")
    )
    if kata:
        saringan = Q()
        for nama_field in CARI_RSVP:
            saringan |= Q(**{f"{nama_field}__icontains": kata})
        qs = qs.filter(saringan)
    return qs


@staf_required
def panel_rsvp(request, pk):
    event = get_object_or_404(SiwakEvent, pk=pk)
    kata = (request.GET.get("q") or "").strip()
    daftar = _rsvp_queryset(event, kata)

    # Ringkasan di atas tabel sengaja dihitung dari seluruh peserta acara, bukan
    # dari hasil pencarian: angka "Sudah check-in" yang ikut menyusut saat
    # panitia mengetik satu nama akan terbaca seperti data yang hilang.
    semua = _rsvp_queryset(event)

    bagian = PETA_BAGIAN["event"]
    return render(request, "siwak/panel/rsvp.html", _kerangka(
        request,
        judul=f"RSVP · {event.judul}",
        bagian="event",
        sumber="event",
        remah=[
            (bagian.nama, reverse("siwak:panel_bagian", args=["event"])),
            ("SIWAK Events", reverse("siwak:panel_daftar", args=["event"])),
            ("RSVP", ""),
        ],
        event=event,
        halaman=Paginator(daftar, PER_HALAMAN).get_page(request.GET.get("page")),
        kata=kata,
        # Kotak cari disembunyikan kalau acaranya memang belum punya peserta:
        # mencari di daftar kosong hanya menambah pertanyaan.
        ada_rsvp=semua.exists(),
        kueri=urlencode({"q": kata}) if kata else "",
        url_kembali=request.get_full_path(),
        pilihan_kehadiran=EventRSVP.KEHADIRAN_STATUS_CHOICES,
        pilihan_kupon=EventRSVP.QR_CHOICES,
        ringkasan_rsvp=[
            ("Total RSVP", semua.count()),
            ("Sudah check-in", semua.filter(status_kehadiran="hadir").count()),
            ("Kupon ditukar", semua.filter(status_kupon="redeemed").count()),
        ],
    ))


@staf_required
def panel_rsvp_csv(request, pk):
    event = get_object_or_404(SiwakEvent, pk=pk)
    # Unduhan mengikuti pencarian yang sedang aktif. Kalau tidak, tombol unduh
    # akan memberi berkas yang isinya berbeda dari yang sedang dilihat panitia.
    kata = (request.GET.get("q") or "").strip()

    respons = HttpResponse(content_type="text/csv; charset=utf-8")
    aman = "".join(c if c.isalnum() else "-" for c in event.judul).strip("-").lower()
    respons["Content-Disposition"] = f'attachment; filename="rsvp-{aman or event.pk}.csv"'

    penulis = csv.writer(respons)
    penulis.writerow(["Nama", "NPM", "Kehadiran", "Alasan izin", "QR Kehadiran", "QR Kupon"])
    for rsvp in _rsvp_queryset(event, kata):
        profil = getattr(rsvp.user, "maba_profile", None)
        penulis.writerow([
            profil.nama_lengkap if profil else rsvp.user.username,
            profil.npm if profil else "",
            rsvp.get_kehadiran_display(),
            rsvp.alasan_izin,
            rsvp.get_status_kehadiran_display(),
            rsvp.get_status_kupon_display() if rsvp.status_kupon else "",
        ])
    return respons


# Dua kolom QR yang bisa disunting dari daftar RSVP. Nilainya:
# (nama field status, nama field cap waktu, pilihan, nilai yang "sudah terjadi").
MEDAN_RSVP = {
    "kehadiran": ("status_kehadiran", "checked_in_at", EventRSVP.KEHADIRAN_STATUS_CHOICES, "hadir"),
    "kupon": ("status_kupon", "redeemed_at", EventRSVP.QR_CHOICES, "redeemed"),
}


@staf_required
@require_POST
def panel_rsvp_status(request, pk):
    """Ubah status QR Kehadiran / QR Kupon satu peserta langsung dari daftarnya.

    Cap waktunya ikut diurus supaya baris ini tetap sama bentuknya dengan hasil
    pindai QR: status yang dinaikkan mendapat waktu sekarang kalau belum punya,
    status yang diturunkan kehilangan cap waktunya. Tanpa itu akan ada baris
    yang tertulis "belum hadir" tapi masih menyimpan jam check-in.
    """
    rsvp = get_object_or_404(EventRSVP, pk=pk)
    cadangan = reverse("siwak:panel_rsvp", args=[rsvp.event_id])

    medan = MEDAN_RSVP.get(request.POST.get("medan") or "")
    if medan is None:
        messages.error(request, "Kolom status yang diminta tidak dikenal.")
        return _kembali(request, cadangan)

    nama_status, nama_waktu, pilihan, nilai_terjadi = medan
    nilai = request.POST.get("nilai") or ""
    if nilai not in dict(pilihan):
        messages.error(request, "Status yang dipilih tidak dikenal.")
        return _kembali(request, cadangan)

    setattr(rsvp, nama_status, nilai)
    if nilai == nilai_terjadi:
        if getattr(rsvp, nama_waktu) is None:
            setattr(rsvp, nama_waktu, timezone.now())
    else:
        setattr(rsvp, nama_waktu, None)
    rsvp.save(update_fields=[nama_status, nama_waktu])

    profil = getattr(rsvp.user, "maba_profile", None)
    nama = profil.nama_lengkap if profil else rsvp.user.username
    messages.success(request, f"{nama} · {dict(pilihan)[nilai]}.")
    return _kembali(request, cadangan)


@staf_required
@require_POST
def panel_rsvp_toggle(request, pk):
    """Buka/tutup RSVP langsung dari daftar acara, tanpa membuka form ubah.

    Tombolnya di daftar selalu memunculkan kotak konfirmasi dulu: menutup RSVP
    di waktu yang salah langsung terasa oleh maba yang sedang mendaftar, jadi
    status ini tidak boleh berubah hanya karena satu klik yang tidak sengaja.
    """
    event = get_object_or_404(SiwakEvent, pk=pk)
    event.rsvp_dibuka = not event.rsvp_dibuka
    event.save(update_fields=["rsvp_dibuka"])
    messages.success(
        request,
        f"RSVP “{event.judul}” sekarang {'dibuka' if event.rsvp_dibuka else 'ditutup'}.",
    )
    return _kembali(request, reverse("siwak:panel_daftar", args=["event"]))


@staf_required
@require_POST
def panel_sesi_aktif(request, pk):
    """Nyalakan/matikan satu sesi mentoring langsung dari daftarnya.

    Status baru dibaca dari kiriman form, bukan sekadar dibalik dari yang
    tersimpan: pengurus sering membuka daftar ini di beberapa tab sekaligus,
    dan saklar yang hanya tahu "kebalikan dari sekarang" akan mematikan sesi
    yang baru saja dinyalakan dari tab sebelah.
    """
    sesi = get_object_or_404(MentoringSession.objects.select_related("kelompok"), pk=pk)
    aktif = request.POST.get("aktif") == "1"
    if aktif != sesi.is_active:
        sesi.is_active = aktif
        sesi.save(update_fields=["is_active"])
    messages.success(
        request,
        f"{sesi.kelompok.nama_kelompok} — {sesi.judul} sekarang "
        f"{'aktif' if aktif else 'nonaktif'}.",
    )
    return _kembali(request, reverse("siwak:panel_daftar", args=["sesi"]))


# ---------------------------------------------------------------------------
# Penyusun pertanyaan tugas
#
# Dua halaman: daftar pertanyaan sebuah tugas, dan form satu pertanyaan
# beserta pilihan jawabannya. Sengaja dipisah — menyusun pilihan ganda di
# dalam daftar yang panjang lebih membingungkan daripada membuka satu form
# yang fokus pada satu pertanyaan.
# ---------------------------------------------------------------------------

PilihanFormSet = inlineformset_factory(
    Question, Choice, form=PilihanForm, fields=["teks"], extra=1, can_delete=True
)

TIPE_PILIHAN_GANDA = "choice"


def _tugas_atau_404(pk):
    return get_object_or_404(Tugas, pk=pk)


def _pertanyaan_terurut(tugas):
    """Pertanyaan tugas ini, urutannya pasti.

    `Question.Meta.ordering` cuma memakai `urutan`, padahal baris yang dibuat
    di luar panel semuanya bernilai 0. Tanpa pk sebagai pemecah seri, urutan
    yang tampil bisa berubah-ubah tiap kali halaman dibuka.
    """
    return tugas.questions.order_by("urutan", "pk")


def _rapikan_urutan(tugas):
    """Tulis ulang urutan jadi 0..n-1 supaya tombol naik/turun punya arti."""
    for posisi, soal in enumerate(_pertanyaan_terurut(tugas)):
        if soal.urutan != posisi:
            Question.objects.filter(pk=soal.pk).update(urutan=posisi)


def _remah_pertanyaan(tugas, judul=""):
    bagian = PETA_BAGIAN["mentoring"]
    remah = [
        (bagian.nama, reverse("siwak:panel_bagian", args=[bagian.slug])),
        ("Tugas", reverse("siwak:panel_daftar", args=["tugas"])),
    ]
    if judul:
        remah.append((tugas.judul_tugas, reverse("siwak:panel_pertanyaan", args=[tugas.pk])))
        remah.append((judul, ""))
    else:
        remah.append((tugas.judul_tugas, ""))
    return remah


@staf_required
def panel_pertanyaan(request, pk):
    """Daftar pertanyaan satu tugas, lengkap dengan pratinjaunya."""
    tugas = _tugas_atau_404(pk)
    _rapikan_urutan(tugas)
    daftar = list(_pertanyaan_terurut(tugas).prefetch_related("choices"))
    terakhir = len(daftar) - 1

    soal = [
        {
            "obj": s,
            "nomor": posisi + 1,
            "label_tipe": PertanyaanForm.TIPE_LABEL.get(s.tipe, s.tipe),
            "pilihan": list(s.choices.order_by("urutan", "pk")),
            "pertama": posisi == 0,
            "terakhir": posisi == terakhir,
        }
        for posisi, s in enumerate(daftar)
    ]

    return render(request, "siwak/panel/pertanyaan.html", _kerangka(
        request,
        judul=f"Pertanyaan — {tugas.judul_tugas}",
        bagian="mentoring",
        sumber="tugas",
        remah=_remah_pertanyaan(tugas),
        tugas=tugas,
        soal=soal,
        url_kembali=request.get_full_path(),
    ))


def _cukup_pilihan(formset):
    """Pilihan ganda tanpa dua pilihan bukan pilihan ganda."""
    terisi = 0
    for form in formset.forms:
        if not hasattr(form, "cleaned_data"):
            continue
        if form.cleaned_data.get("DELETE"):
            continue
        if (form.cleaned_data.get("teks") or "").strip():
            terisi += 1
    return terisi >= 2


def _simpan_pertanyaan(request, tugas, instance=None):
    """Form satu pertanyaan + pilihan jawabannya, dipakai tambah dan ubah."""
    ubah = instance is not None

    if request.method == "POST":
        form = PertanyaanForm(request.POST, instance=instance)
        formset = PilihanFormSet(request.POST, instance=instance)

        if form.is_valid():
            # Disusun dulu tanpa menyentuh basis data: pertanyaan baru yang
            # pilihannya belum sah jangan sempat tersimpan setengah jadi.
            soal = form.save(commit=False)
            soal.tugas = tugas
            if not ubah:
                terakhir = tugas.questions.aggregate(n=Max("urutan"))["n"]
                soal.urutan = 0 if terakhir is None else terakhir + 1

            if soal.tipe != TIPE_PILIHAN_GANDA:
                soal.save()
                # Bukan pilihan ganda: jangan sisakan pilihan yatim yang tidak
                # akan pernah tampil ke maba.
                dibuang = soal.choices.count()
                soal.choices.all().delete()
                catatan = f" {dibuang} pilihan jawaban ikut dihapus." if dibuang else ""
                messages.success(request, f"Pertanyaan “{soal}” berhasil disimpan.{catatan}")
                return redirect("siwak:panel_pertanyaan", pk=tugas.pk)

            formset = PilihanFormSet(request.POST, instance=soal)
            if formset.is_valid() and _cukup_pilihan(formset):
                with transaction.atomic():
                    soal.save()
                    formset.instance = soal
                    formset.save()
                messages.success(request, f"Pertanyaan “{soal}” berhasil disimpan.")
                return redirect("siwak:panel_pertanyaan", pk=tugas.pk)

            if formset.is_valid():
                form.add_error(None, "Pilihan ganda butuh minimal dua pilihan jawaban.")
            messages.error(request, "Masih ada isian yang perlu dibetulkan.")
        else:
            messages.error(request, "Masih ada isian yang perlu dibetulkan.")
    else:
        form = PertanyaanForm(instance=instance)
        formset = PilihanFormSet(instance=instance)

    judul = "Ubah Pertanyaan" if ubah else "Tambah Pertanyaan"
    return render(request, "siwak/panel/pertanyaan_form.html", _kerangka(
        request,
        judul=judul,
        bagian="mentoring",
        sumber="tugas",
        remah=_remah_pertanyaan(tugas, judul),
        tugas=tugas,
        form=form,
        formset=formset,
        objek=instance,
        url_batal=reverse("siwak:panel_pertanyaan", args=[tugas.pk]),
        url_hapus=(
            reverse("siwak:panel_pertanyaan_hapus", args=[instance.pk]) if ubah else ""
        ),
    ))


@staf_required
def panel_pertanyaan_tambah(request, pk):
    return _simpan_pertanyaan(request, _tugas_atau_404(pk))


@staf_required
def panel_pertanyaan_ubah(request, pk):
    soal = get_object_or_404(Question.objects.select_related("tugas"), pk=pk)
    return _simpan_pertanyaan(request, soal.tugas, instance=soal)


@staf_required
@require_POST
def panel_pertanyaan_hapus(request, pk):
    soal = get_object_or_404(Question.objects.select_related("tugas"), pk=pk)
    tugas = soal.tugas
    nama = str(soal)
    soal.delete()
    _rapikan_urutan(tugas)
    messages.success(request, f"Pertanyaan “{nama}” berhasil dihapus.")
    return redirect("siwak:panel_pertanyaan", pk=tugas.pk)


@staf_required
@require_POST
def panel_pertanyaan_urut(request, pk):
    """Tukar posisi satu pertanyaan dengan tetangganya."""
    soal = get_object_or_404(Question.objects.select_related("tugas"), pk=pk)
    tugas = soal.tugas
    naik = request.POST.get("arah") != "turun"

    with transaction.atomic():
        # Dirapikan dulu: kalau dua baris sama-sama bernilai 0, menukarnya
        # tidak mengubah apa pun dan tombolnya terlihat rusak.
        _rapikan_urutan(tugas)
        soal.refresh_from_db()
        tetangga = (
            _pertanyaan_terurut(tugas).filter(urutan__lt=soal.urutan).last()
            if naik
            else _pertanyaan_terurut(tugas).filter(urutan__gt=soal.urutan).first()
        )
        if tetangga is not None:
            Question.objects.filter(pk=soal.pk).update(urutan=tetangga.urutan)
            Question.objects.filter(pk=tetangga.pk).update(urutan=soal.urutan)

    return _kembali(request, reverse("siwak:panel_pertanyaan", args=[tugas.pk]))


# ---------------------------------------------------------------------------
# Pemeriksa jawaban tugas — hanya baca.
# Jawaban adalah kiriman maba; panel ini untuk memeriksa dan mengunduhnya,
# bukan untuk menyuntingnya. Karena itu tidak ada view ubah maupun hapus.
# ---------------------------------------------------------------------------

CARI_JAWABAN = (
    "user__maba_profile__nama_lengkap",
    "user__maba_profile__npm",
    "user__username",
)


def _jawaban_queryset(tugas, kata=""):
    qs = (
        tugas.submissions.select_related("user__maba_profile")
        .prefetch_related("answers__question", "answers__selected_choice")
        .order_by("user__maba_profile__nama_lengkap", "user__username")
    )
    if kata:
        saring = Q()
        for nama_field in CARI_JAWABAN:
            saring |= Q(**{f"{nama_field}__icontains": kata})
        qs = qs.filter(saring)
    return qs


def _isi_jawaban(jawaban):
    """Satu jawaban jadi tulisan siap tampil, apa pun tipenya."""
    if jawaban.selected_choice_id:
        return jawaban.selected_choice.teks
    if jawaban.file_answer:
        return jawaban.file_answer.name.split("/")[-1]
    return jawaban.text_answer


def _pasangkan_jawaban(pengumpulan, pertanyaan):
    """Pasangkan tiap pertanyaan dengan jawabannya, termasuk yang belum diisi."""
    peta = {j.question_id: j for j in pengumpulan.answers.all()}
    baris = []
    for soal in pertanyaan:
        jawaban = peta.get(soal.pk)
        baris.append({
            "pertanyaan": soal,
            "jawaban": jawaban,
            "isi": _isi_jawaban(jawaban) if jawaban else "",
        })
    return baris


@staf_required
def panel_jawaban(request, pk):
    tugas = _tugas_atau_404(pk)
    pertanyaan = list(_pertanyaan_terurut(tugas))
    kata = (request.GET.get("q") or "").strip()

    halaman = Paginator(_jawaban_queryset(tugas, kata), PER_HALAMAN).get_page(
        request.GET.get("page")
    )
    baris = []
    for pengumpulan in halaman.object_list:
        profil = getattr(pengumpulan.user, "maba_profile", None)
        pasangan = _pasangkan_jawaban(pengumpulan, pertanyaan)
        baris.append({
            "obj": pengumpulan,
            "nama": profil.nama_lengkap if profil else pengumpulan.user.username,
            "npm": profil.npm if profil else "—",
            "jawaban": pasangan,
            "jumlah_terisi": sum(1 for p in pasangan if p["isi"]),
        })

    semua = tugas.submissions.all()
    return render(request, "siwak/panel/jawaban.html", _kerangka(
        request,
        judul=f"Jawaban — {tugas.judul_tugas}",
        bagian="mentoring",
        sumber="tugas",
        remah=_remah_pertanyaan(tugas, "Jawaban"),
        tugas=tugas,
        pertanyaan=pertanyaan,
        baris=baris,
        halaman=halaman,
        kata=kata,
        kueri=urlencode({k: v for k, v in request.GET.items() if k != "page" and v}),
        jumlah_semua=semua.count(),
        jumlah_terlambat=semua.filter(status="late").count(),
    ))


@staf_required
def panel_jawaban_csv(request, pk):
    """Unduhan mengikuti pencarian yang sedang aktif, sama seperti ekspor RSVP."""
    tugas = _tugas_atau_404(pk)
    pertanyaan = list(_pertanyaan_terurut(tugas))
    kata = (request.GET.get("q") or "").strip()

    respons = HttpResponse(content_type="text/csv")
    nama_berkas = slugify(tugas.judul_tugas) or "tugas"
    respons["Content-Disposition"] = f'attachment; filename="jawaban_{nama_berkas}.csv"'

    penulis = csv.writer(respons)
    penulis.writerow(
        ["Nama", "NPM", "Status", "Waktu Kumpul"] + [s.pertanyaan for s in pertanyaan]
    )
    for pengumpulan in _jawaban_queryset(tugas, kata):
        profil = getattr(pengumpulan.user, "maba_profile", None)
        peta = {j.question_id: j for j in pengumpulan.answers.all()}
        penulis.writerow(
            [
                profil.nama_lengkap if profil else pengumpulan.user.username,
                profil.npm if profil else "",
                pengumpulan.get_status_display(),
                timezone.localtime(pengumpulan.submitted_at).strftime("%Y-%m-%d %H:%M"),
            ]
            + [_isi_jawaban(peta[s.pk]) if s.pk in peta else "" for s in pertanyaan]
        )
    return respons
