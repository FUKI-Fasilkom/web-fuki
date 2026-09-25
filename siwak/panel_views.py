"""View panel pengelola SIWAK (/siwak/admin/).

Empat view CRUD di bawah (`panel_daftar`, `panel_tambah`, `panel_ubah`,
`panel_hapus`) melayani *semua* jenis data yang terdaftar di `panel.py`. Yang
membedakan satu menu dengan menu lain hanyalah isi `Sumber`-nya, bukan kodenya.

Di luar itu ada dua kelompok view kecil: halaman khusus yang memang tidak
berbentuk CRUD biasa (konten halaman utama, detail satu kelompok mentoring,
detail satu mentee, dan daftar RSVP per acara), dan penyunting langsung
(`panel_set_kelompok`, `panel_set_role`, `panel_set_link`, `panel_set_npm`) yang
dipanggil dari dropdown atau isian di halaman daftar tanpa membuka form ubah.
"""

import csv
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, F, Max, Prefetch, ProtectedError, Q
from django.forms import inlineformset_factory
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import (
    AssessmentAspect,
    AssignmentReview,
    AssignmentReviewHistory,
    Choice,
    EventRSVP,
    KelompokMentoring,
    MenteeAssessment,
    MentoringAttendance,
    Profile,
    RSVPTertunda,
    MentoringSession,
    Question,
    SiwakEvent,
    SiwakInfo,
    Tugas,
    TugasSubmission,
)
from .panel import (
    BAGIAN,
    HALAMAN_KHUSUS,
    PETA_BAGIAN,
    PETA_SUMBER,
    daftar_kelompok,
    daftar_role,
    sumber_bagian,
)
from .panel_forms import InfoSiwakForm, PertanyaanForm, PilihanForm, RsvpProfilForm
from .services.rsvp import buat_rsvp, klaim_rsvp_tertunda

PER_HALAMAN = 25

# Tipe kolom yang isinya dropdown penyunting relasi, bukan sekadar tulisan.
# Dipakai untuk menentukan daftar pilihan apa yang perlu ikut dikirim ke templat.
TIPE_BUTUH_KELOMPOK = {"pilih_kelompok", "pilih_kelompok_mentor"}
TIPE_BUTUH_ROLE = {"pilih_role"}


def staf_required(view_func):
    """Hanya untuk pengurus. Mengikuti pola `pemindai_required` di views.py:
    yang belum login diarahkan ke login admin, yang sudah login tapi bukan staf
    mendapat 403 — bukan dilempar balik ke halaman login berulang-ulang.

    Akun pemindai QR sengaja selalu `is_staff=False` (lihat AkunPemindaiForm),
    jadi decorator inilah yang menutup seluruh panel untuknya."""

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
    # Sama dengan "pilih_kelompok": beda hanya di label dan hitungan kapasitas.
    "pilih_kelompok_mentor": "siwak:panel_set_kelompok",
    "pilih_role": "siwak:panel_set_role",
    "isi_link": "siwak:panel_set_link",
    "isi_npm": "siwak:panel_set_npm",
    "saklar_rsvp": "siwak:panel_rsvp_toggle",
    "pilih_aktif": "siwak:panel_sesi_aktif",
}


def _sel(obj, sumber, nomor):
    """Ubah satu objek jadi daftar sel siap render. `nomor` = urutan baris ini
    di seluruh daftar (bukan di halamannya), dipakai kolom bertipe "nomor"."""
    daftar = []
    for k in sumber.kolom:
        butir = {
            "judul": k.judul, "tipe": k.tipe,
            "nilai": nomor if k.tipe == "nomor" else k.ambil(obj),
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
        {
            "label": a.label(obj),
            "url": reverse(a.nama_url, args=[a.pk(obj) if a.pk else obj.pk]),
            "bawa_kembali": a.bawa_kembali,
        }
        for a in sumber.aksi_baris
    ]


def _saring(qs, sumber, request):
    """Terapkan dropdown penyaring milik `sumber` dari alamat halaman.

    Mengembalikan queryset tersaring, dropdown siap render, dan apakah ada
    penyaring yang aktif. Nilai dicocokkan dengan pilihannya lebih dulu: nilai
    yang tidak dikenal diabaikan, bukan dikirim ke query.
    """
    dropdown = []
    aktif = False
    for saringan in sumber.saringan:
        pilihan = [(str(nilai), label) for nilai, label in saringan.pilihan()]
        nilai = (request.GET.get(saringan.kunci) or "").strip()
        if nilai not in dict(pilihan):
            nilai = ""
        if nilai:
            qs = qs.filter(**{saringan.lookup: nilai})
            aktif = True
        dropdown.append({
            "kunci": saringan.kunci,
            "label": saringan.label,
            "pilihan": pilihan,
            "terpilih": nilai,
        })
    return qs, dropdown, aktif


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
                {"label": s.label_jamak, "jumlah": s.ambil_queryset().count()}
                for s in daftar
            ],
        })

    mentee = Profile.objects.filter(role=Profile.ROLE_MENTEE)
    ringkasan = [
        ("Mentee", mentee.count()),
        ("Kelompok mentoring", KelompokMentoring.objects.count()),
        ("Mentor", Profile.objects.filter(role=Profile.ROLE_MENTOR).count()),
        ("Belum punya kelompok", mentee.filter(kelompok__isnull=True).count()),
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
            "jumlah": sumber.ambil_queryset().count(),
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
    qs, saringan, ada_saringan = _saring(qs, sumber, request)

    qs, kunci_urut, turun = _urutkan(qs, sumber, request)

    halaman = Paginator(qs, PER_HALAMAN).get_page(request.GET.get("page"))
    baris = [
        {"obj": o, "pk": o.pk, "sel": _sel(o, sumber, nomor), "aksi": _aksi(o, sumber)}
        for nomor, o in enumerate(halaman.object_list, start=halaman.start_index())
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
    if tipe_kolom & TIPE_BUTUH_ROLE:
        ekstra["daftar_role"] = daftar_role()

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
        saringan=saringan,
        ada_saringan=ada_saringan,
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
    if not sumber.boleh_ubah:
        raise Http404("Jenis data ini tidak bisa diubah dari panel.")
    return _simpan(request, sumber, get_object_or_404(sumber.ambil_queryset(), pk=pk))


@staf_required
@require_POST
def panel_hapus(request, slug, pk):
    sumber = _sumber_atau_404(slug)
    if not sumber.boleh_hapus:
        raise Http404("Jenis data ini tidak bisa dihapus dari panel.")
    objek = get_object_or_404(sumber.ambil_queryset(), pk=pk)
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
    """Ganti kelompok satu mahasiswa langsung dari daftar Peserta atau daftar Mentor.

    `pk` adalah Profile — mentee maupun mentor — karena `kelompok` kini
    kolom di profilnya sendiri; tidak ada lagi dua penyunting yang berbeda.
    Memilih kelompok lain memindahkannya, memilih pilihan kosong melepasnya.
    Mentor yang dipindahkan ke kelompok yang sudah punya mentor tidak
    menggantikan siapa pun: sebuah kelompok memang boleh dipegang lebih dari satu.
    """
    profil = get_object_or_404(Profile, pk=pk)
    mentor = profil.is_mentor
    cadangan = reverse("siwak:panel_daftar", args=["mentor" if mentor else "peserta"])

    if profil.role is None:
        messages.error(
            request,
            f"{profil.nama_lengkap} belum punya role, jadi belum bisa ditempatkan di kelompok.",
        )
        return _kembali(request, reverse("siwak:panel_daftar", args=["profil"]))

    pilihan = _angka(request.POST.get("kelompok"))
    kelompok = KelompokMentoring.objects.filter(pk=pilihan).first() if pilihan else None
    if pilihan and kelompok is None:
        messages.error(request, "Kelompok yang dipilih sudah tidak ada.")
        return _kembali(request, cadangan)

    if profil.kelompok_id != (kelompok.pk if kelompok else None):
        profil.kelompok = kelompok
        profil.save(update_fields=["kelompok"])
        if mentor:
            pesan = (
                f"{profil.nama_lengkap} sekarang memegang {kelompok.nama_kelompok}." if kelompok
                else f"{profil.nama_lengkap} tidak lagi memegang kelompok."
            )
        else:
            pesan = (
                f"{profil.nama_lengkap} dipindahkan ke {kelompok.nama_kelompok}." if kelompok
                else f"{profil.nama_lengkap} dikeluarkan dari kelompoknya."
            )
        messages.success(request, pesan)
    return _kembali(request, cadangan)


@staf_required
@require_POST
def panel_set_role(request, pk):
    """Tetapkan role satu profil (Mentee / Mentor / kosong) dari daftar Profile.

    Role menentukan daftar mana yang memuatnya, dan `kelompok` berarti hal yang
    berbeda di tiap role (mentee: kelompok tempat dia jadi peserta, mentor:
    kelompok yang dia pegang). Karena itu kelompoknya dilepas setiap kali role
    berubah — kalau tidak, mentee yang dijadikan mentor otomatis memegang
    kelompok tempat dia tadinya jadi peserta. Presensi, nilai, dan feedback
    yang sudah tercatat menempel di profilnya, jadi tidak ikut hilang.
    """
    profil = get_object_or_404(Profile, pk=pk)
    cadangan = reverse("siwak:panel_daftar", args=["profil"])

    role = (request.POST.get("role") or "").strip() or None
    if role is not None and role not in dict(Profile.ROLE_CHOICES):
        messages.error(request, "Role yang dipilih tidak dikenal.")
        return _kembali(request, cadangan)

    if profil.role != role:
        lepas = profil.kelompok_id is not None
        profil.role = role
        profil.kelompok = None
        profil.save(update_fields=["role", "kelompok"])
        pesan = (
            f"{profil.nama_lengkap} sekarang {profil.get_role_display()}." if role
            else f"Role {profil.nama_lengkap} dikosongkan."
        )
        if lepas:
            pesan += " Kelompok sebelumnya dilepas."
        messages.success(request, pesan)
    return _kembali(request, cadangan)


@staf_required
@require_POST
def panel_set_link(request, pk):
    """Ganti link grup WhatsApp satu kelompok langsung dari daftar Kelompok Mentoring.

    Isian kosong menghapus link (kelompok itu lalu ditandai "Belum ada link").
    Validasinya validasi field model yang sama dengan form Ubah, jadi kedua jalan
    menerima dan menolak hal yang persis sama.
    """
    kelompok = get_object_or_404(KelompokMentoring, pk=pk)
    cadangan = reverse("siwak:panel_daftar", args=["kelompok"])

    link = (request.POST.get("link_grup") or "").strip()
    try:
        link = KelompokMentoring._meta.get_field("link_grup").clean(link, kelompok)
    except ValidationError as galat:
        messages.error(
            request,
            f"Link grup {kelompok.nama_kelompok} tidak disimpan: {galat.messages[0]}",
        )
        return _kembali(request, cadangan)

    if link != kelompok.link_grup:
        kelompok.link_grup = link
        kelompok.save(update_fields=["link_grup"])
        messages.success(
            request,
            f"Link grup {kelompok.nama_kelompok} diperbarui." if link
            else f"Link grup {kelompok.nama_kelompok} dihapus.",
        )
    return _kembali(request, cadangan)


@staf_required
@require_POST
def panel_set_npm(request, pk):
    """Isi/ganti NPM satu mentor SSO langsung dari daftar Mentor.

    Hanya untuk mentor SSO: NPM mentor non-SSO harus tetap NULL (itulah yang
    menjaga akun lokal dan akun CAS tidak pernah bertabrakan), dan NPM mentee
    punya jalurnya sendiri lewat form Ubah. Kosong ditolak, seperti di
    `MentorForm`: NPM satu-satunya cara barisnya diklaim saat orangnya login SSO.
    """
    profil = get_object_or_404(
        Profile, pk=pk, role=Profile.ROLE_MENTOR, auth_source=Profile.SOURCE_SSO
    )
    cadangan = reverse("siwak:panel_daftar", args=["mentor"])

    npm = (request.POST.get("npm") or "").strip()
    panjang_maks = Profile._meta.get_field("npm").max_length
    if not npm:
        galat = "NPM tidak boleh kosong; NPM yang menyambungkan mentor ini ke akun SSO-nya."
    elif not npm.isdigit() or len(npm) > panjang_maks:
        galat = f"NPM harus berupa angka saja, paling banyak {panjang_maks} digit."
    else:
        galat = ""
        pemilik = Profile.objects.filter(npm=npm).exclude(pk=profil.pk).first()
        if pemilik:
            galat = f"NPM {npm} sudah dipakai {pemilik.nama_lengkap}."

    if not galat and profil.npm != npm:
        profil.npm = npm
        try:
            with transaction.atomic():
                profil.save(update_fields=["npm"])
        except IntegrityError:
            # Kalah balapan dengan pengurus lain yang baru saja memakai NPM yang sama.
            galat = f"NPM {npm} sudah dipakai profil lain."
        else:
            messages.success(request, f"NPM {profil.nama_lengkap} diperbarui.")

    if galat:
        messages.error(request, f"NPM {profil.nama_lengkap} tidak disimpan: {galat}")
    return _kembali(request, cadangan)


@staf_required
def panel_profil_rsvp(request, pk):
    """Pengelola membuatkan RSVP untuk satu profil, dari daftar Profile/Mentee/Mentor.

    Hasilnya sama dengan RSVP lewat web (token QR registrasi & kupon, status belum
    check-in, kupon belum ditukar). Profil yang sudah punya akun login langsung
    mendapat `EventRSVP`. Yang belum ditampung sebagai `RSVPTertunda` dan menjadi
    `EventRSVP` (dengan token yang sama) saat orangnya login SSO — sama seperti
    `seed_rsvp`. RSVP yang sudah ada tidak ditimpa: mengubah statusnya lewat
    daftar RSVP acara, menghapusnya pun di sana.
    """
    profil = get_object_or_404(Profile.objects.select_related("user", "kelompok"), pk=pk)
    cadangan = reverse("siwak:panel_daftar", args=["profil"])
    kembali = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(
        kembali, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        kembali = ""

    # Profil tanpa akun hanya bisa diklaim lewat NPM-nya saat login SSO. Tanpa NPM,
    # RSVP tertunda tidak akan pernah menemukan pemiliknya.
    if profil.user_id is None and not profil.npm:
        messages.error(
            request,
            f"{profil.nama_lengkap} belum punya akun login maupun NPM, jadi RSVP-nya "
            "tidak akan tersambung. Isi NPM-nya dulu.",
        )
        return redirect(kembali or cadangan)

    if profil.user_id:
        # Sisa RSVP tertunda (akun ditautkan tanpa lewat login SSO) dijadikan RSVP dulu.
        klaim_rsvp_tertunda(profil)

    form = RsvpProfilForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        event = form.cleaned_data["event"]
        kehadiran = form.cleaned_data["kehadiran"]
        alasan = form.cleaned_data["alasan_izin"]
        tertunda = RSVPTertunda.objects.filter(event=event, profile=profil).first()

        if profil.user_id and EventRSVP.objects.filter(event=event, user_id=profil.user_id).exists():
            form.add_error(
                "event",
                f"{profil.nama_lengkap} sudah punya RSVP untuk {event.judul}. "
                "Ubah atau hapus lewat daftar RSVP acara itu.",
            )
        elif profil.user_id:
            buat_rsvp(event=event, user=profil.user, kehadiran=kehadiran, alasan_izin=alasan)
            messages.success(request, f"RSVP {profil.nama_lengkap} untuk {event.judul} dibuat.")
            return _kembali(request, cadangan)
        elif tertunda is None:
            RSVPTertunda.objects.create(
                event=event, profile=profil, kehadiran=kehadiran, alasan_izin=alasan
            )
            messages.success(
                request,
                f"RSVP {profil.nama_lengkap} untuk {event.judul} dibuat. Belum punya akun login, "
                "jadi RSVP-nya aktif otomatis begitu dia login SSO.",
            )
            return _kembali(request, cadangan)
        else:
            # Sudah pernah dibuatkan dan orangnya belum login: jawabannya boleh
            # dikoreksi, token QR-nya tetap supaya tidak ada QR yang berubah.
            tertunda.kehadiran, tertunda.alasan_izin = kehadiran, alasan
            tertunda.save(update_fields=["kehadiran", "alasan_izin"])
            messages.success(
                request, f"RSVP {profil.nama_lengkap} untuk {event.judul} diperbarui."
            )
            return _kembali(request, cadangan)

    # Keadaan RSVP orang ini di setiap acara, supaya pengelola tahu sebelum menyimpan.
    sudah = {}
    if profil.user_id:
        sudah = {r.event_id: r for r in EventRSVP.objects.filter(user_id=profil.user_id)}
    menunggu = {r.event_id: r for r in RSVPTertunda.objects.filter(profile=profil)}
    acara = []
    for event in form.fields["event"].queryset:
        if event.pk in sudah:
            keadaan = f"Sudah RSVP · {sudah[event.pk].get_kehadiran_display()}"
        elif event.pk in menunggu:
            keadaan = f"Menunggu login · {menunggu[event.pk].get_kehadiran_display()}"
        else:
            keadaan = "Belum RSVP"
        acara.append({"event": event, "keadaan": keadaan})

    sumber_asal = PETA_SUMBER["profil"]
    bagian = PETA_BAGIAN[sumber_asal.bagian]
    return render(request, "siwak/panel/profil_rsvp.html", _kerangka(
        request,
        judul=f"Buat RSVP · {profil.nama_lengkap}",
        bagian=sumber_asal.bagian,
        sumber="profil",
        remah=[
            (bagian.nama, reverse("siwak:panel_bagian", args=[bagian.slug])),
            (sumber_asal.label_jamak, kembali or cadangan),
            ("Buat RSVP", ""),
        ],
        profil=profil,
        form=form,
        acara=acara,
        url_kembali=kembali,
        url_batal=kembali or cadangan,
    ))


# ---------------------------------------------------------------------------
# Detail satu kelompok mentoring — hanya baca
# ---------------------------------------------------------------------------

@staf_required
def panel_kelompok_detail(request, pk):
    """Satu kelompok lengkap: mentor, seluruh mentee, dan rekap presensinya.

    Daftar Kelompok hanya muat nama mentor dan jumlah mentee; halaman ini yang
    menjawab "siapa saja isinya". Sengaja hanya baca: memindahkan anggota tetap
    lewat dropdown di daftar Mentee dan Mentor, supaya aturan penempatannya
    (role wajib ada, kelompok dilepas saat role berubah) tidak punya jalur kedua.

    Presensi dibaca sebagai satu kisi mentee × sesi; `?sesi=<nomor>` menyempitkan
    kisinya ke satu sesi. Catatan milik mentee yang sudah pindah kelompok tidak
    ikut: yang ditampilkan isi kelompok sekarang. Detail per mentee (nilai per
    aspek, jawaban tugas, feedback) ada di halaman detail mentee.
    """
    kelompok = get_object_or_404(KelompokMentoring, pk=pk)
    mentor = list(kelompok.daftar_mentor.select_related("user").order_by("nama_lengkap"))
    mentee = list(kelompok.daftar_mentee.select_related("user").order_by("nama_lengkap"))
    semua_sesi = list(kelompok.mentoring_sessions.order_by("nomor"))

    sesi_dipilih = (request.GET.get("sesi") or "").strip()
    if sesi_dipilih not in {str(s.nomor) for s in semua_sesi}:
        sesi_dipilih = ""
    sesi = [s for s in semua_sesi if not sesi_dipilih or str(s.nomor) == sesi_dipilih]

    presensi = {
        (peserta_id, sesi_id): status
        for peserta_id, sesi_id, status in MentoringAttendance.objects.filter(
            session__kelompok=kelompok, peserta__in=mentee
        ).values_list("peserta_id", "session_id", "status")
    }
    label_status = dict(MentoringAttendance.STATUS_CHOICES)

    # Tugas berlaku untuk semua kelompok, jadi yang dihitung cukup tugas aktif
    # yang sudah dikumpulkan tiap mentee (lewat akun loginnya), dan berapa di
    # antaranya yang sudah dinilai mentor.
    tugas_aktif = Tugas.objects.filter(is_active=True).count()
    terkumpul = dict(
        TugasSubmission.objects.filter(
            tugas__is_active=True, user__profil__in=mentee
        ).values("user__profil").annotate(n=Count("pk")).values_list("user__profil", "n")
    )
    dinilai = dict(
        AssignmentReview.objects.filter(
            submission__tugas__is_active=True, submission__user__profil__in=mentee
        ).values("submission__user__profil").annotate(n=Count("pk"))
        .values_list("submission__user__profil", "n")
    )
    # Rata-rata aspek yang masih aktif, sama dengan yang dilihat mentor.
    rata_nilai = dict(
        MenteeAssessment.objects.filter(peserta__in=mentee, aspect__is_active=True)
        .values("peserta").annotate(rata=Avg("score")).values_list("peserta", "rata")
    )

    baris = []
    for m in mentee:
        status = [presensi.get((m.pk, s.pk)) for s in sesi]
        rata = rata_nilai.get(m.pk)
        baris.append({
            "profil": m,
            "presensi": [{"status": st or "", "label": label_status.get(st, "—")} for st in status],
            "hadir": status.count(MentoringAttendance.STATUS_HADIR),
            "tugas": terkumpul.get(m.pk, 0),
            "dinilai": dinilai.get(m.pk, 0),
            "rata_nilai": round(rata, 1) if rata is not None else None,
        })

    kolom_sesi = [
        {
            "sesi": s,
            "hadir": sum(
                presensi.get((m.pk, s.pk)) == MentoringAttendance.STATUS_HADIR for m in mentee
            ),
        }
        for s in sesi
    ]

    bagian = PETA_BAGIAN["kelompok"]
    return render(request, "siwak/panel/kelompok_detail.html", _kerangka(
        request,
        judul=kelompok.nama_kelompok,
        bagian="kelompok",
        sumber="kelompok",
        remah=[
            (bagian.nama, reverse("siwak:panel_bagian", args=[bagian.slug])),
            ("Kelompok Mentoring", reverse("siwak:panel_daftar", args=["kelompok"])),
            (kelompok.nama_kelompok, ""),
        ],
        kelompok=kelompok,
        mentor=mentor,
        baris=baris,
        kolom_sesi=kolom_sesi,
        pilihan_sesi=semua_sesi,
        sesi_dipilih=sesi_dipilih,
        sesi_aktif=sum(s.is_active for s in semua_sesi),
        tugas_aktif=tugas_aktif,
    ))


@staf_required
def panel_mentee_detail(request, pk):
    """Semua yang tercatat tentang satu mentee, untuk diperiksa pengurus.

    Presensi dan feedback tiap sesi, nilai per aspek, serta setiap tugas beserta
    jawaban, nilai, feedback, dan riwayat penilaian mentornya. Semuanya hanya
    baca — yang mengisinya mentor dari portalnya — kecuali catatan privat, yang
    disimpan lewat `mentee_catatan` (pintu yang sama dengan halaman mentor).

    Sesi kelompok lama ikut tampil kalau mentee ini punya presensi atau feedback
    di sana, mis. sesudah dipindah kelompok: data itu tetap miliknya.
    """
    mentee = get_object_or_404(
        Profile.objects.select_related("kelompok", "user"), pk=pk, role=Profile.ROLE_MENTEE
    )
    kelompok = mentee.kelompok
    mentor = list(kelompok.daftar_mentor.order_by("nama_lengkap")) if kelompok else []

    presensi = {
        a.session_id: a
        for a in mentee.mentoring_attendance.select_related("session__kelompok", "recorded_by")
    }
    feedback = {}
    for entry in mentee.mentor_feedback.select_related("session__kelompok", "mentor").order_by("created_at"):
        feedback.setdefault(entry.session_id, []).append(entry)
    sesi = {
        s.pk: s
        for s in (kelompok.mentoring_sessions.select_related("kelompok") if kelompok else [])
    }
    for a in presensi.values():
        sesi.setdefault(a.session_id, a.session)
    for entries in feedback.values():
        for entry in entries:
            sesi.setdefault(entry.session_id, entry.session)
    baris_sesi = [
        {"sesi": s, "presensi": presensi.get(s.pk), "feedback": feedback.get(s.pk, [])}
        for s in sorted(
            sesi.values(),
            key=lambda s: (s.kelompok_id != mentee.kelompok_id, s.kelompok.nama_kelompok, s.nomor),
        )
    ]

    # Aspek aktif selalu tampil (kosong = belum dinilai); aspek yang sudah
    # dimatikan hanya tampil kalau mentee ini sempat dinilai di sana.
    nilai = {n.aspect_id: n for n in mentee.assessments.select_related("aspect", "assessed_by")}
    baris_nilai = [
        {"aspek": aspek, "nilai": nilai.get(aspek.pk)}
        for aspek in AssessmentAspect.objects.order_by("urutan", "nama")
        if aspek.is_active or aspek.pk in nilai
    ]
    skor_aktif = [n.score for n in nilai.values() if n.aspect.is_active]

    submissions = (
        TugasSubmission.objects.filter(user=mentee.user)
        .select_related("mentor_review__reviewer")
        .prefetch_related(
            "answers__question",
            "answers__selected_choice",
            Prefetch(
                "mentor_review_history",
                queryset=AssignmentReviewHistory.objects.select_related("reviewer"),
            ),
        )
        if mentee.user_id
        else TugasSubmission.objects.none()
    )
    per_tugas = {s.tugas_id: s for s in submissions}
    baris_tugas = []
    for tugas in Tugas.objects.order_by("deadline"):
        submission = per_tugas.get(tugas.pk)
        baris_tugas.append({
            "tugas": tugas,
            "submission": submission,
            "review": getattr(submission, "mentor_review", None) if submission else None,
            "riwayat": list(submission.mentor_review_history.all()) if submission else [],
        })

    bagian = PETA_BAGIAN["kelompok"]
    return render(request, "siwak/panel/mentee_detail.html", _kerangka(
        request,
        judul=mentee.nama_lengkap,
        bagian="kelompok",
        sumber="peserta",
        remah=[
            (bagian.nama, reverse("siwak:panel_bagian", args=[bagian.slug])),
            ("Mentee", reverse("siwak:panel_daftar", args=["peserta"])),
            (mentee.nama_lengkap, ""),
        ],
        mentee=mentee,
        kelompok=kelompok,
        mentor=mentor,
        baris_sesi=baris_sesi,
        jumlah_hadir=sum(
            a.status == MentoringAttendance.STATUS_HADIR for a in presensi.values()
        ),
        baris_nilai=baris_nilai,
        rata_nilai=round(sum(skor_aktif) / len(skor_aktif), 1) if skor_aktif else None,
        baris_tugas=baris_tugas,
        jumlah_terkumpul=sum(1 for b in baris_tugas if b["submission"]),
        jumlah_dinilai=sum(1 for b in baris_tugas if b["review"]),
        url_kembali=request.get_full_path(),
    ))


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
    "user__profil__nama_lengkap",
    "user__profil__npm",
    "user__username",
)


# Tab saringan peran di atas daftar RSVP: (nilai ?role=, label). "" = semua.
TAB_PERAN_RSVP = [
    ("", "Semua"),
    (Profile.ROLE_MENTOR, "Mentor"),
    (Profile.ROLE_MENTEE, "Mentee"),
]


def _peran_rsvp(request):
    """Peran yang disaring lewat `?role=`, atau "" untuk semua peserta.

    Huruf besar ikut diterima (`?role=MENTOR`): alamat ini sering diketik dan
    dibagikan tangan antarpanitia. Nilai lain diabaikan, bukan 404 — saringan
    yang salah ketik lebih baik jatuh ke "semua" daripada halaman rusak.
    """
    peran = (request.GET.get("role") or "").strip().lower()
    return peran if peran in dict(Profile.ROLE_CHOICES) else ""


def _rsvp_queryset(event, kata="", peran=""):
    qs = (
        EventRSVP.objects.filter(event=event)
        .select_related("user__profil")
        .order_by("user__profil__nama_lengkap", "user__username")
    )
    if peran:
        qs = qs.filter(user__profil__role=peran)
    if kata:
        saringan = Q()
        for nama_field in CARI_RSVP:
            saringan |= Q(**{f"{nama_field}__icontains": kata})
        qs = qs.filter(saringan)
    return qs


def _hitung_rsvp(event):
    """Semua angka ringkasan RSVP satu acara, dalam satu query.

    Kuncinya "semua", "mentor", "mentee" (terdaftar), masing-masing dengan
    akhiran "_hadir" (sudah check-in), plus "kupon" (kupon ditukar). Peserta
    tanpa profil atau tanpa role hanya terhitung di "semua" — karena itu
    semua ≠ mentor + mentee, dan templat menyebut sisanya.
    """
    hadir = Q(status_kehadiran="hadir")
    mentor = Q(user__profil__role=Profile.ROLE_MENTOR)
    mentee = Q(user__profil__role=Profile.ROLE_MENTEE)
    return EventRSVP.objects.filter(event=event).aggregate(
        semua=Count("pk"),
        semua_hadir=Count("pk", filter=hadir),
        kupon=Count("pk", filter=Q(status_kupon="redeemed")),
        mentor=Count("pk", filter=mentor),
        mentor_hadir=Count("pk", filter=mentor & hadir),
        mentee=Count("pk", filter=mentee),
        mentee_hadir=Count("pk", filter=mentee & hadir),
    )


@staf_required
def panel_rsvp(request, pk):
    event = get_object_or_404(SiwakEvent, pk=pk)
    kata = (request.GET.get("q") or "").strip()
    peran = _peran_rsvp(request)
    daftar = _rsvp_queryset(event, kata, peran)

    # Ringkasan di atas tabel sengaja dihitung dari seluruh peserta acara, bukan
    # dari hasil pencarian atau tab peran: angka "Sudah check-in" yang ikut
    # menyusut saat panitia mengetik satu nama akan terbaca seperti data yang
    # hilang. Angka per peran punya tempatnya sendiri, di tab saringannya.
    angka = _hitung_rsvp(event)
    # RSVP dari form lain yang orangnya belum login SSO: belum jadi EventRSVP,
    # jadi tidak ada di `angka` dan tidak ikut "Total RSVP" maupun tab peran.
    menunggu = RSVPTertunda.objects.filter(event=event).count()

    # Berpindah tab tetap membawa pencarian yang sedang aktif, dan sebaliknya
    # (lihat input tersembunyi di form cari), supaya dua saringan ini bisa
    # dipakai bersamaan.
    tab_peran = []
    for nilai, label in TAB_PERAN_RSVP:
        kunci = nilai or "semua"
        params = {k: v for k, v in (("q", kata), ("role", nilai)) if v}
        tab_peran.append({
            "nilai": nilai,
            "label": label,
            "hadir": angka[f"{kunci}_hadir"],
            "terdaftar": angka[kunci],
            "url": f"?{urlencode(params)}" if params else request.path,
            "aktif": nilai == peran,
        })

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
        peran=peran,
        label_peran=dict(TAB_PERAN_RSVP)[peran],
        tab_peran=tab_peran,
        tanpa_peran=angka["semua"] - angka["mentor"] - angka["mentee"],
        # Kotak cari disembunyikan kalau acaranya memang belum punya peserta:
        # mencari di daftar kosong hanya menambah pertanyaan.
        ada_rsvp=angka["semua"] > 0,
        kueri=urlencode({k: v for k, v in (("q", kata), ("role", peran)) if v}),
        url_kembali=request.get_full_path(),
        pilihan_kehadiran=EventRSVP.KEHADIRAN_STATUS_CHOICES,
        pilihan_kupon=EventRSVP.QR_CHOICES,
        ringkasan_rsvp=[
            ("Total RSVP", angka["semua"]),
            ("Sudah check-in", angka["semua_hadir"]),
            ("Kupon ditukar", angka["kupon"]),
            ("Menunggu login", menunggu),
        ],
        rsvp_menunggu=menunggu,
    ))


@staf_required
def panel_rsvp_csv(request, pk):
    event = get_object_or_404(SiwakEvent, pk=pk)
    # Unduhan mengikuti pencarian dan tab peran yang sedang aktif. Kalau tidak,
    # tombol unduh akan memberi berkas yang isinya berbeda dari yang sedang
    # dilihat panitia.
    kata = (request.GET.get("q") or "").strip()
    peran = _peran_rsvp(request)

    respons = HttpResponse(content_type="text/csv; charset=utf-8")
    aman = "".join(c if c.isalnum() else "-" for c in event.judul).strip("-").lower()
    respons["Content-Disposition"] = f'attachment; filename="rsvp-{aman or event.pk}.csv"'

    penulis = csv.writer(respons)
    penulis.writerow(["Nama", "NPM", "Peran", "Kehadiran", "Alasan izin", "QR Kehadiran", "QR Kupon"])
    for rsvp in _rsvp_queryset(event, kata, peran):
        profil = getattr(rsvp.user, "profil", None)
        penulis.writerow([
            profil.nama_lengkap if profil else rsvp.user.username,
            profil.npm if profil else "",
            profil.get_role_display() if profil and profil.role else "",
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

    profil = getattr(rsvp.user, "profil", None)
    nama = profil.nama_lengkap if profil else rsvp.user.username
    messages.success(request, f"{nama} · {dict(pilihan)[nilai]}.")
    return _kembali(request, cadangan)


@staf_required
@require_POST
def panel_rsvp_hapus(request, pk):
    """Hapus satu baris RSVP dari daftar peserta acara.

    Peserta yang RSVP-nya dihapus bisa mendaftar lagi selama RSVP acara masih
    dibuka; QR lamanya tidak berlaku lagi karena barisnya sudah tidak ada.
    """
    rsvp = get_object_or_404(EventRSVP.objects.select_related("user__profil"), pk=pk)
    cadangan = reverse("siwak:panel_rsvp", args=[rsvp.event_id])

    profil = getattr(rsvp.user, "profil", None)
    nama = profil.nama_lengkap if profil else rsvp.user.username
    rsvp.delete()
    messages.success(request, f"RSVP {nama} berhasil dihapus.")
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
    "user__profil__nama_lengkap",
    "user__profil__npm",
    "user__username",
)


def _jawaban_queryset(tugas, kata=""):
    qs = (
        tugas.submissions.select_related("user__profil")
        .prefetch_related("answers__question", "answers__selected_choice")
        .order_by("user__profil__nama_lengkap", "user__username")
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
        profil = getattr(pengumpulan.user, "profil", None)
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
        profil = getattr(pengumpulan.user, "profil", None)
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
