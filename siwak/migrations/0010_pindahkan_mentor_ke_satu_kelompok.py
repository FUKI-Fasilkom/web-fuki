"""Pindahkan penugasan mentor dari tabel ManyToMany ke kolom FK di Mentor.

Selama ini satu mentor bisa terdaftar di banyak kelompok. Aturannya sekarang
satu mentor satu kelompok, jadi kalau ada mentor yang terlanjur memegang lebih
dari satu, yang dipakai adalah kelompok pertama berdasarkan namanya dan
sisanya dicatat lewat peringatan supaya pengurus tahu apa yang perlu dibetulkan
di panel — bukan hilang diam-diam.
"""

from django.db import migrations


def ke_kolom_mentor(apps, schema_editor):
    KelompokMentoring = apps.get_model("siwak", "KelompokMentoring")
    Mentor = apps.get_model("siwak", "Mentor")

    dipegang = {}
    for kelompok in KelompokMentoring.objects.order_by("nama_kelompok"):
        for mentor in kelompok.mentors.all():
            dipegang.setdefault(mentor.pk, []).append(kelompok)

    for mentor_pk, daftar in dipegang.items():
        Mentor.objects.filter(pk=mentor_pk).update(kelompok=daftar[0])
        if len(daftar) > 1:
            nama = Mentor.objects.get(pk=mentor_pk).nama
            lepas = ", ".join(k.nama_kelompok for k in daftar[1:])
            print(
                f"  ! {nama} tadinya memegang {len(daftar)} kelompok; "
                f"dipertahankan di {daftar[0].nama_kelompok}, dilepas dari {lepas}."
            )


def kembalikan(apps, schema_editor):
    Mentor = apps.get_model("siwak", "Mentor")
    for mentor in Mentor.objects.exclude(kelompok__isnull=True).select_related("kelompok"):
        mentor.kelompok.mentors.add(mentor)


class Migration(migrations.Migration):

    dependencies = [
        ("siwak", "0009_mentor_pegang_satu_kelompok"),
    ]

    operations = [
        migrations.RunPython(ke_kolom_mentor, kembalikan),
    ]
