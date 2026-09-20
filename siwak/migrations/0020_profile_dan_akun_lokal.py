"""Generalisasi MahasiswaProfile -> Profile, dan siapkan akun mentor non-SSO.

Ditulis tangan, bukan hasil `makemigrations`, karena pertanyaan rename-nya
interaktif: dengan `--noinput` Django memilih DeleteModel + CreateModel yang
menghapus seluruh baris profil. RenameModel hanya me-rename tabel.

Semua operasi di sini non-destruktif (rename tabel, satu kolom jadi nullable,
satu kolom baru ber-default), jadi aman dijalankan dalam satu deploy.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("siwak", "0019_hapus_berkas_utama_submission"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="MahasiswaProfile",
            new_name="Profile",
        ),
        migrations.AlterModelOptions(
            name="profile",
            options={
                "ordering": ["nama_lengkap"],
                "verbose_name": "Profil",
                "verbose_name_plural": "Profil",
            },
        ),
        migrations.AlterField(
            model_name="profile",
            name="user",
            field=models.OneToOneField(
                blank=True,
                help_text="Terisi otomatis saat orangnya login lewat SSO UI. Boleh kosong.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="profil",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Akun login",
            ),
        ),
        # Mentor non-SSO tidak punya NPM sama sekali. UNIQUE tetap dipertahankan:
        # Postgres memperlakukan tiap NULL sebagai berbeda.
        migrations.AlterField(
            model_name="profile",
            name="npm",
            field=models.CharField(
                blank=True, max_length=20, null=True, unique=True, verbose_name="NPM"
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="auth_source",
            field=models.CharField(
                choices=[("sso", "SSO UI"), ("lokal", "Akun lokal")],
                default="sso",
                max_length=10,
                verbose_name="Sumber akun",
            ),
        ),
    ]
