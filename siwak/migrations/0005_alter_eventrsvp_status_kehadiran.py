# Generated manually (local env can't run makemigrations):
# converts EventRSVP.status_kehadiran to the hadir / belum_hadir enum
# and backfills legacy values ('registered', 'unused', 'redeemed', NULL).

from django.db import migrations, models


def forwards(apps, schema_editor):
    EventRSVP = apps.get_model("siwak", "EventRSVP")
    # NULL rows don't match `exclude(...)`, so backfill them explicitly first.
    EventRSVP.objects.filter(status_kehadiran__isnull=True).update(status_kehadiran="belum_hadir")
    EventRSVP.objects.exclude(status_kehadiran="hadir").exclude(
        status_kehadiran="belum_hadir"
    ).update(status_kehadiran="belum_hadir")


def backwards(apps, schema_editor):
    EventRSVP = apps.get_model("siwak", "EventRSVP")
    EventRSVP.objects.filter(status_kehadiran="belum_hadir").update(status_kehadiran="unused")


class Migration(migrations.Migration):

    dependencies = [
        ('siwak', '0004_rename_catatan_eventrsvp_alasan_izin_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name='eventrsvp',
            name='status_kehadiran',
            field=models.CharField(
                choices=[('hadir', 'Hadir'), ('belum_hadir', 'Belum Hadir')],
                default='belum_hadir',
                max_length=12,
            ),
        ),
    ]