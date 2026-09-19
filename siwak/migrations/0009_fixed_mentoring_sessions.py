from django.db import migrations, models


def configure_fixed_sessions(apps, schema_editor):
    KelompokMentoring = apps.get_model("siwak", "KelompokMentoring")
    MentoringSession = apps.get_model("siwak", "MentoringSession")

    for group in KelompokMentoring.objects.all().iterator():
        existing_sessions = list(
            MentoringSession.objects.filter(kelompok=group).order_by("tanggal", "pk")
        )
        if len(existing_sessions) > 4:
            raise RuntimeError(
                f"Kelompok {group.pk} memiliki lebih dari 4 sesi mentoring. "
                "Rapikan data sesi sebelum menjalankan migrasi ini."
            )

        used_numbers = set()
        for number, session in enumerate(existing_sessions, start=1):
            session.nomor = number
            session.judul = f"Sesi Mentoring {number}"
            session.is_active = True
            session.save(update_fields=["nomor", "judul", "is_active"])
            used_numbers.add(number)

        MentoringSession.objects.bulk_create(
            [
                MentoringSession(
                    kelompok=group,
                    nomor=number,
                    judul=f"Sesi Mentoring {number}",
                    is_active=False,
                )
                for number in range(1, 5)
                if number not in used_numbers
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("siwak", "0008_move_mentor_group_relation"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="mentoringsession",
            options={
                "ordering": ["kelompok", "nomor"],
                "verbose_name": "Sesi Mentoring",
                "verbose_name_plural": "Sesi Mentoring",
            },
        ),
        migrations.AddField(
            model_name="mentoringsession",
            name="is_active",
            field=models.BooleanField(default=False, verbose_name="Aktif"),
        ),
        migrations.AddField(
            model_name="mentoringsession",
            name="nomor",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                choices=[(1, "Sesi 1"), (2, "Sesi 2"), (3, "Sesi 3"), (4, "Sesi 4")],
                editable=False,
                verbose_name="Sesi",
            ),
        ),
        migrations.AlterField(
            model_name="mentoringsession",
            name="judul",
            field=models.CharField(
                editable=False,
                max_length=200,
                verbose_name="Nama/Sesi Mentoring",
            ),
        ),
        migrations.AlterField(
            model_name="mentoringsession",
            name="tanggal",
            field=models.DateField(blank=True, null=True, verbose_name="Tanggal Mentoring"),
        ),
        migrations.RunPython(configure_fixed_sessions, migrations.RunPython.noop),
    ]
