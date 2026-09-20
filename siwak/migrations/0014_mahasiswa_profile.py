"""Siapkan skema untuk menyatukan MabaProfile, PesertaMentoring, dan Mentor.

Ini langkah 1 dari 3 (0014 skema -> 0015 data -> 0016 pembersihan). Sengaja
dipecah: di PostgreSQL, mengubah data lalu ALTER TABLE dalam satu transaksi
gagal dengan "pending trigger events", jadi tiap tahap dapat transaksinya
sendiri.

Yang dikerjakan di sini hanya menambah, tidak ada yang dihapus:

- MabaProfile diganti nama jadi MahasiswaProfile, dan mendapat `role` serta
  `kelompok`.
- Delapan kolom sementara `*_profil` ditambahkan ke tabel yang selama ini
  menunjuk Mentor / PesertaMentoring. Angka di kolom lama adalah PK Mentor atau
  PK PesertaMentoring, jadi kolom itu TIDAK BOLEH langsung diarahkan ke
  MahasiswaProfile — angkanya akan menunjuk baris yang salah tanpa ada error.
  Migrasi 0015 mengisi kolom sementara ini lewat pemetaan PK lama -> PK baru.
- Tiga kolom `peserta` lama dibuat boleh NULL untuk sementara. Ini yang membuat
  migrasi ini bisa dibalik: saat 0016 dibalik, kolom lama muncul lagi dalam
  keadaan kosong dan baru diisi ulang oleh 0015 (arah mundur).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

MENTOR_SAJA = {"role": "mentor"}


def _profil_mentor(related_name, *, blank):
    return models.ForeignKey(
        blank=blank,
        null=True,
        limit_choices_to=MENTOR_SAJA,
        on_delete=django.db.models.deletion.SET_NULL,
        related_name=related_name,
        to="siwak.mahasiswaprofile",
    )


def _profil_peserta(related_name):
    # Non-null di akhir (0016); NULL dulu selama data belum dipindahkan.
    return models.ForeignKey(
        null=True,
        on_delete=django.db.models.deletion.CASCADE,
        related_name=related_name,
        to="siwak.mahasiswaprofile",
    )


def _peserta_lama_boleh_null(related_name):
    return models.ForeignKey(
        null=True,
        on_delete=django.db.models.deletion.CASCADE,
        related_name=related_name,
        to="siwak.pesertamentoring",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("siwak", "0013_mentor_features"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel(old_name="MabaProfile", new_name="MahasiswaProfile"),
        migrations.AlterModelOptions(
            name="mahasiswaprofile",
            options={
                "ordering": ["nama_lengkap"],
                "verbose_name": "Profil Mahasiswa",
                "verbose_name_plural": "Profil Mahasiswa",
            },
        ),
        migrations.AlterField(
            model_name="mahasiswaprofile",
            name="user",
            field=models.OneToOneField(
                blank=True,
                help_text="Terisi otomatis saat orangnya login lewat SSO UI. Boleh kosong.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="mahasiswa_profile",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Akun login",
            ),
        ),
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
                    ("SI-IUP", "Sistem Informasi (International Undergraduate Program)"),
                ],
                max_length=10,
                verbose_name="Jurusan",
            ),
        ),
        migrations.AddField(
            model_name="mahasiswaprofile",
            name="role",
            field=models.CharField(
                choices=[("mentee", "Mentee"), ("mentor", "Mentor")],
                default="mentee",
                max_length=10,
                verbose_name="Peran",
            ),
        ),
        migrations.AddField(
            model_name="mahasiswaprofile",
            name="kelompok",
            field=models.ForeignKey(
                blank=True,
                help_text="Mentee: kelompok tempat dia jadi peserta. Mentor: kelompok yang dia pegang.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="anggota",
                to="siwak.kelompokmentoring",
                verbose_name="Kelompok",
            ),
        ),
        # Kolom `peserta` lama boleh NULL sementara (lihat docstring).
        migrations.AlterField(
            model_name="mentoringattendance",
            name="peserta",
            field=_peserta_lama_boleh_null("mentoring_attendance"),
        ),
        migrations.AlterField(
            model_name="menteeassessment",
            name="peserta",
            field=_peserta_lama_boleh_null("assessments"),
        ),
        migrations.AlterField(
            model_name="mentorfeedback",
            name="peserta",
            field=_peserta_lama_boleh_null("mentor_feedback"),
        ),
        # Kolom sementara: 0015 mengisi, 0016 menggantikan kolom lama dengan ini.
        migrations.AddField(
            model_name="mentoringattendance",
            name="peserta_profil",
            field=_profil_peserta("mentoring_attendance"),
        ),
        migrations.AddField(
            model_name="mentoringattendance",
            name="recorded_by_profil",
            field=_profil_mentor("recorded_attendance", blank=True),
        ),
        migrations.AddField(
            model_name="menteeassessment",
            name="peserta_profil",
            field=_profil_peserta("assessments"),
        ),
        migrations.AddField(
            model_name="menteeassessment",
            name="assessed_by_profil",
            field=_profil_mentor("mentee_assessments", blank=True),
        ),
        migrations.AddField(
            model_name="mentorfeedback",
            name="peserta_profil",
            field=_profil_peserta("mentor_feedback"),
        ),
        migrations.AddField(
            model_name="mentorfeedback",
            name="mentor_profil",
            field=_profil_mentor("feedback_entries", blank=False),
        ),
        migrations.AddField(
            model_name="assignmentreview",
            name="reviewer_profil",
            field=_profil_mentor("assignment_reviews", blank=False),
        ),
        migrations.AddField(
            model_name="assignmentreviewhistory",
            name="reviewer_profil",
            field=_profil_mentor("assignment_review_history", blank=False),
        ),
    ]
