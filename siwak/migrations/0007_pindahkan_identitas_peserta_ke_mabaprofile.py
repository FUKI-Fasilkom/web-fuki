"""Pindahkan identitas peserta (nama, NPM, jurusan) dari PesertaMentoring ke MabaProfile.

Setelah migrasi ini PesertaMentoring hanya menyimpan satu hal: peserta mana ada
di kelompok mana. Identitasnya tinggal satu tempat, yaitu MabaProfile, sehingga
tidak ada lagi nama yang berbeda antara profil SSO dan data kelompok.

Peserta lama yang belum punya NPM tetap dibawa: mereka diberi NPM sementara
berawalan "TANPA-NPM-" supaya syarat unik NPM di MabaProfile tidak jebol.
Pengelola tinggal membetulkannya lewat panel SIWAK.
"""

from django.db import migrations


def ke_mabaprofile(apps, schema_editor):
    PesertaMentoring = apps.get_model("siwak", "PesertaMentoring")
    MabaProfile = apps.get_model("siwak", "MabaProfile")

    for peserta in PesertaMentoring.objects.all():
        profil = None

        if peserta.user_id:
            profil = MabaProfile.objects.filter(user_id=peserta.user_id).first()
        if profil is None and peserta.npm:
            profil = MabaProfile.objects.filter(npm=peserta.npm).first()

        if profil is None:
            npm = peserta.npm or f"TANPA-NPM-{peserta.pk}"
            # Dua peserta dengan NPM sama tidak mungkin punya dua profil.
            profil, _ = MabaProfile.objects.get_or_create(
                npm=npm,
                defaults={
                    "user_id": peserta.user_id,
                    "nama_lengkap": peserta.nama_lengkap,
                    "jurusan": peserta.jurusan,
                    "angkatan": "",
                },
            )

        # Satu MabaProfile hanya boleh dipegang satu baris peserta (OneToOne).
        if PesertaMentoring.objects.filter(maba_id=profil.pk).exclude(pk=peserta.pk).exists():
            peserta.delete()
            continue

        peserta.maba_id = profil.pk
        peserta.save(update_fields=["maba"])


def kembalikan(apps, schema_editor):
    PesertaMentoring = apps.get_model("siwak", "PesertaMentoring")

    for peserta in PesertaMentoring.objects.select_related("maba"):
        if not peserta.maba_id:
            continue
        peserta.nama_lengkap = peserta.maba.nama_lengkap
        peserta.jurusan = peserta.maba.jurusan
        peserta.npm = "" if peserta.maba.npm.startswith("TANPA-NPM-") else peserta.maba.npm
        peserta.user_id = peserta.maba.user_id
        peserta.save(update_fields=["nama_lengkap", "jurusan", "npm", "user"])


class Migration(migrations.Migration):

    dependencies = [
        ("siwak", "0006_pesertamentoring_maba_alter_eventrsvp_alasan_izin_and_more"),
    ]

    operations = [
        migrations.RunPython(ke_mabaprofile, kembalikan),
    ]
