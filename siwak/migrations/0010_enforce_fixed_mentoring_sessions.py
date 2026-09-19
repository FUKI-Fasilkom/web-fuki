from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("siwak", "0009_fixed_mentoring_sessions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="mentoringsession",
            name="nomor",
            field=models.PositiveSmallIntegerField(
                choices=[(1, "Sesi 1"), (2, "Sesi 2"), (3, "Sesi 3"), (4, "Sesi 4")],
                editable=False,
                verbose_name="Sesi",
            ),
        ),
        migrations.AddConstraint(
            model_name="mentoringsession",
            constraint=models.UniqueConstraint(
                fields=("kelompok", "nomor"),
                name="unique_mentoring_session_number_per_group",
            ),
        ),
        migrations.AddConstraint(
            model_name="mentoringsession",
            constraint=models.CheckConstraint(
                condition=models.Q(nomor__gte=1, nomor__lte=4),
                name="mentoring_session_number_between_1_and_4",
            ),
        ),
    ]
