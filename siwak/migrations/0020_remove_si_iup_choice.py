from django.db import migrations, models


def gabungkan_si_iup_ke_si(apps, schema_editor):
    MahasiswaProfile = apps.get_model("siwak", "MahasiswaProfile")
    MahasiswaProfile.objects.filter(jurusan="SI-IUP").update(jurusan="SI")


class Migration(migrations.Migration):

    dependencies = [
        ("siwak", "0019_hapus_berkas_utama_submission"),
    ]

    operations = [
        migrations.RunPython(gabungkan_si_iup_ke_si, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="mahasiswaprofile",
            name="jurusan",
            field=models.CharField(
                blank=True,
                choices=[
                    ("IK", "Ilmu Komputer"),
                    ("SI", "Sistem Informasi"),
                    ("KA", "Kecerdasan Artifisial"),
                    ("IK-IUP", "Ilmu Komputer (International Undergraduate Program)"),
                ],
                max_length=10,
                verbose_name="Jurusan",
            ),
        ),
    ]
