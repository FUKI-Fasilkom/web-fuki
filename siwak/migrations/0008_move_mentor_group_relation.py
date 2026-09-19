import django.db.models.deletion
from django.db import migrations, models


def move_existing_mentor_groups(apps, schema_editor):
    Mentor = apps.get_model("siwak", "Mentor")
    KelompokMentoring = apps.get_model("siwak", "KelompokMentoring")

    for mentor in Mentor.objects.all():
        group_ids = list(
            KelompokMentoring.objects.filter(mentors=mentor)
            .order_by("pk")
            .values_list("pk", flat=True)[:2]
        )
        if len(group_ids) > 1:
            raise RuntimeError(
                f"Mentor id={mentor.pk} masih terhubung ke beberapa kelompok. "
                "Pilih satu kelompok sebelum menjalankan migration 0008."
            )
        if group_ids:
            mentor.kelompok_id = group_ids[0]
            mentor.save(update_fields=["kelompok"])


def restore_mentor_group_links(apps, schema_editor):
    Mentor = apps.get_model("siwak", "Mentor")
    KelompokMentoring = apps.get_model("siwak", "KelompokMentoring")

    for mentor in Mentor.objects.exclude(kelompok_id=None):
        group = KelompokMentoring.objects.get(pk=mentor.kelompok_id)
        group.mentors.add(mentor)


class Migration(migrations.Migration):

    dependencies = [
        ("siwak", "0007_alter_eventrsvp_alasan_izin"),
    ]

    operations = [
        migrations.AddField(
            model_name="mentor",
            name="kelompok",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="mentors",
                to="siwak.kelompokmentoring",
                verbose_name="Kelompok Mentoring",
            ),
        ),
        migrations.RunPython(
            move_existing_mentor_groups,
            restore_mentor_group_links,
        ),
        migrations.RemoveField(
            model_name="kelompokmentoring",
            name="mentors",
        ),
    ]
