"""Hapus Mentor dan PesertaMentoring; kolom sementara jadi kolom sungguhan.

Langkah 3 dari 3 (lihat 0014 dan 0015). Pada titik ini 0015 sudah mengisi
kedelapan kolom `*_profil`, jadi kolom lama yang menunjuk Mentor /
PesertaMentoring aman dibuang.

Urutannya penting:

1. Dua constraint unik yang menyebut `peserta` dibuang lebih dulu — kolom yang
   dirujuk constraint tidak bisa dihapus.
2. Kolom lama dibuang, lalu kedua model dihapus (tidak ada lagi yang menunjuk).
3. Kolom `*_profil` diganti nama menjadi nama aslinya (`peserta`, `reviewer`, ...).
4. Tiga kolom `peserta` dikembalikan menjadi NOT NULL. Kalau ada satu saja yang
   masih NULL, langkah ini gagal keras — itu memang yang diinginkan: lebih baik
   migrasi berhenti daripada penilaian kehilangan pesertanya diam-diam.
5. Constraint unik dipasang lagi di atas kolom baru.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("siwak", "0015_gabungkan_profil_mahasiswa"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="mentoringattendance",
            name="unique_attendance_per_session_participant",
        ),
        migrations.RemoveConstraint(
            model_name="menteeassessment",
            name="unique_assessment_per_participant_aspect",
        ),
        migrations.RemoveField(model_name="mentoringattendance", name="peserta"),
        migrations.RemoveField(model_name="mentoringattendance", name="recorded_by"),
        migrations.RemoveField(model_name="menteeassessment", name="peserta"),
        migrations.RemoveField(model_name="menteeassessment", name="assessed_by"),
        migrations.RemoveField(model_name="mentorfeedback", name="peserta"),
        migrations.RemoveField(model_name="mentorfeedback", name="mentor"),
        migrations.RemoveField(model_name="assignmentreview", name="reviewer"),
        migrations.RemoveField(model_name="assignmentreviewhistory", name="reviewer"),
        migrations.DeleteModel(name="PesertaMentoring"),
        migrations.DeleteModel(name="Mentor"),
        migrations.RenameField(
            model_name="mentoringattendance", old_name="peserta_profil", new_name="peserta"
        ),
        migrations.RenameField(
            model_name="mentoringattendance", old_name="recorded_by_profil", new_name="recorded_by"
        ),
        migrations.RenameField(
            model_name="menteeassessment", old_name="peserta_profil", new_name="peserta"
        ),
        migrations.RenameField(
            model_name="menteeassessment", old_name="assessed_by_profil", new_name="assessed_by"
        ),
        migrations.RenameField(
            model_name="mentorfeedback", old_name="peserta_profil", new_name="peserta"
        ),
        migrations.RenameField(
            model_name="mentorfeedback", old_name="mentor_profil", new_name="mentor"
        ),
        migrations.RenameField(
            model_name="assignmentreview", old_name="reviewer_profil", new_name="reviewer"
        ),
        migrations.RenameField(
            model_name="assignmentreviewhistory", old_name="reviewer_profil", new_name="reviewer"
        ),
        migrations.AlterField(
            model_name="mentoringattendance",
            name="peserta",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="mentoring_attendance",
                to="siwak.mahasiswaprofile",
            ),
        ),
        migrations.AlterField(
            model_name="menteeassessment",
            name="peserta",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="assessments",
                to="siwak.mahasiswaprofile",
            ),
        ),
        migrations.AlterField(
            model_name="mentorfeedback",
            name="peserta",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="mentor_feedback",
                to="siwak.mahasiswaprofile",
            ),
        ),
        migrations.AddConstraint(
            model_name="mentoringattendance",
            constraint=models.UniqueConstraint(
                fields=("session", "peserta"),
                name="unique_attendance_per_session_participant",
            ),
        ),
        migrations.AddConstraint(
            model_name="menteeassessment",
            constraint=models.UniqueConstraint(
                fields=("peserta", "aspect"),
                name="unique_assessment_per_participant_aspect",
            ),
        ),
    ]
