"""Gabungkan Mentor dan PesertaMentoring ke dalam MahasiswaProfile.

Langkah 2 dari 3 (data saja, tidak ada ALTER TABLE — lihat 0014).

Arah maju:

1. Tiap PesertaMentoring: `kelompok`-nya disalin ke profilnya (`maba`).
2. Tiap Mentor dicarikan profilnya, lalu profil itu dijadikan `role="mentor"`
   dengan `kelompok` milik Mentor. Urutan pencarian (yang pertama kena menang):
     a. profil milik `mentor.user` — satu akun tidak boleh punya dua profil;
     b. profil ber-NPM sama yang belum dipegang akun lain. Profil yang sudah
        ada pemiliknya sengaja dilewati supaya NPM yang kebetulan sama tidak
        bisa mengubah role milik orang lain (aturan yang sama dengan
        `sync_mahasiswa_profile` di sso.py);
     c. kalau tidak ada, profil baru. Mentor tanpa NPM diberi NPM sementara
        berawalan "TANPA-NPM-MENTOR-", idiom yang sama dengan migrasi 0007.
3. Kalau orang yang sama tercatat sebagai peserta di satu kelompok dan mentor
   di kelompok lain, MENTOR MENANG dan perbedaannya dicetak sebagai peringatan
   supaya pengurus tahu, bukan hilang diam-diam (gaya migrasi 0010).
4. Delapan kolom sementara `*_profil` diisi lewat pemetaan PK lama -> PK profil.
   Inilah inti migrasi ini: angka di kolom lama adalah PK Mentor /
   PesertaMentoring, dan tanpa pemetaan ini angkanya akan menunjuk profil yang
   salah tanpa ada error.

Tidak perlu dedup untuk constraint unik (session, peserta) dan (peserta, aspect):
PesertaMentoring.maba adalah OneToOne, jadi pemetaan peserta -> profil injektif.

Arah mundur membangun ulang Mentor dan PesertaMentoring dari profil, lalu
mengisi kolom lama dari kolom sementara. Profil ber-role mentee dibuatkan
PesertaMentoring; profil ber-role mentor dibuatkan Mentor. Profil ber-NPM
sementara ("TANPA-NPM-MENTOR-...") dibuang karena skema lama tidak punya
padanannya.
"""

from django.db import migrations

TANPA_NPM = "TANPA-NPM-"
TANPA_NPM_MENTOR = "TANPA-NPM-MENTOR-"

# (model, kolom lama, kolom sementara, pemetaan yang dipakai)
JEJAK = [
    ("MentoringAttendance", "peserta", "peserta_profil", "peserta"),
    ("MentoringAttendance", "recorded_by", "recorded_by_profil", "mentor"),
    ("MenteeAssessment", "peserta", "peserta_profil", "peserta"),
    ("MenteeAssessment", "assessed_by", "assessed_by_profil", "mentor"),
    ("MentorFeedback", "peserta", "peserta_profil", "peserta"),
    ("MentorFeedback", "mentor", "mentor_profil", "mentor"),
    ("AssignmentReview", "reviewer", "reviewer_profil", "mentor"),
    ("AssignmentReviewHistory", "reviewer", "reviewer_profil", "mentor"),
]


def _nama_kelompok(Kelompok, pk):
    if pk is None:
        return "(tanpa kelompok)"
    kelompok = Kelompok.objects.filter(pk=pk).first()
    return kelompok.nama_kelompok if kelompok else f"#{pk}"


def _cari_atau_buat_profil(Profil, mentor):
    if mentor.user_id:
        profil = Profil.objects.filter(user_id=mentor.user_id).first()
        if profil is not None:
            return profil

    if mentor.npm:
        calon = Profil.objects.filter(npm=mentor.npm).first()
        if calon is not None:
            if calon.user_id is None or calon.user_id == mentor.user_id:
                if calon.user_id is None and mentor.user_id:
                    calon.user_id = mentor.user_id
                return calon
            print(
                f"  ! NPM {mentor.npm} milik mentor {mentor.nama} sudah dipakai profil "
                f"akun lain; profil mentor dibuat baru dengan NPM sementara."
            )

    npm = mentor.npm
    if not npm or Profil.objects.filter(npm=npm).exists():
        npm = f"{TANPA_NPM_MENTOR}{mentor.pk}"
    return Profil.objects.create(
        npm=npm,
        nama_lengkap=mentor.nama,
        jurusan="",
        angkatan="",
        user_id=mentor.user_id,
    )


def gabungkan(apps, schema_editor):
    Profil = apps.get_model("siwak", "MahasiswaProfile")
    Peserta = apps.get_model("siwak", "PesertaMentoring")
    Mentor = apps.get_model("siwak", "Mentor")
    Kelompok = apps.get_model("siwak", "KelompokMentoring")

    peta_peserta = {}
    for peserta in Peserta.objects.all():
        peta_peserta[peserta.pk] = peserta.maba_id
        Profil.objects.filter(pk=peserta.maba_id).update(kelompok_id=peserta.kelompok_id)

    peta_mentor = {}
    for mentor in Mentor.objects.order_by("pk"):
        profil = _cari_atau_buat_profil(Profil, mentor)

        # Profil dimuat setelah kelompok peserta disalin di atas, jadi ini nilai terkini.
        sebelumnya = profil.kelompok_id
        if sebelumnya and sebelumnya != mentor.kelompok_id:
            print(
                f"  ! {profil.nama_lengkap} tadinya peserta {_nama_kelompok(Kelompok, sebelumnya)} "
                f"dan mentor {_nama_kelompok(Kelompok, mentor.kelompok_id)}; "
                f"dipertahankan sebagai mentor."
            )

        profil.role = "mentor"
        profil.kelompok_id = mentor.kelompok_id
        profil.save()
        peta_mentor[mentor.pk] = profil.pk

    peta = {"peserta": peta_peserta, "mentor": peta_mentor}
    for nama_model, lama, baru, jenis in JEJAK:
        Model = apps.get_model("siwak", nama_model)
        for pk_lama, pk_profil in peta[jenis].items():
            Model.objects.filter(**{lama: pk_lama}).update(**{baru: pk_profil})


def kembalikan(apps, schema_editor):
    Profil = apps.get_model("siwak", "MahasiswaProfile")
    Peserta = apps.get_model("siwak", "PesertaMentoring")
    Mentor = apps.get_model("siwak", "Mentor")

    # Profil yang dirujuk kolom `peserta` harus punya PesertaMentoring, sekalipun
    # rolenya mentor (orang yang sama pernah dinilai sebagai peserta) — kalau
    # tidak, FK-nya akan kosong dan penilaian itu hilang.
    dirujuk = set()
    for nama_model in ("MentoringAttendance", "MenteeAssessment", "MentorFeedback"):
        Model = apps.get_model("siwak", nama_model)
        dirujuk.update(
            Model.objects.exclude(peserta_profil__isnull=True)
            .values_list("peserta_profil_id", flat=True)
        )

    peta_peserta = {}
    perlu_peserta = set(Profil.objects.filter(role="mentee").values_list("pk", flat=True)) | dirujuk
    for profil in Profil.objects.filter(pk__in=perlu_peserta):
        peserta = Peserta.objects.create(maba_id=profil.pk, kelompok_id=profil.kelompok_id)
        peta_peserta[profil.pk] = peserta.pk

    peta_mentor = {}
    for profil in Profil.objects.filter(role="mentor"):
        mentor = Mentor.objects.create(
            nama=profil.nama_lengkap,
            npm=None if profil.npm.startswith(TANPA_NPM) else profil.npm,
            user_id=profil.user_id,
            kelompok_id=profil.kelompok_id,
        )
        peta_mentor[profil.pk] = mentor.pk

    peta = {"peserta": peta_peserta, "mentor": peta_mentor}
    for nama_model, lama, baru, jenis in JEJAK:
        Model = apps.get_model("siwak", nama_model)
        for pk_profil, pk_lama in peta[jenis].items():
            Model.objects.filter(**{baru: pk_profil}).update(**{lama: pk_lama})

    # Profil ber-NPM sementara dibuat arah-maju khusus untuk mentor tanpa NPM;
    # skema lama tidak punya padanannya (mentor lama tidak punya profil maba).
    # Dibuang paling akhir — setelah kolom lama terisi — supaya maju-mundur
    # berulang tidak menumpuk profil kosong. Profil yang juga dirujuk sebagai
    # peserta dipertahankan.
    Profil.objects.filter(
        role="mentor", npm__startswith=TANPA_NPM_MENTOR
    ).exclude(pk__in=dirujuk).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("siwak", "0014_mahasiswa_profile"),
    ]

    operations = [
        migrations.RunPython(gabungkan, kembalikan),
    ]
