import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def seed_assessment_aspects(apps, schema_editor):
    AssessmentAspect = apps.get_model("siwak", "AssessmentAspect")
    for order, name in enumerate(("Keaktifan", "Pemahaman Materi", "Kehadiran"), start=1):
        AssessmentAspect.objects.get_or_create(
            nama=name,
            defaults={"urutan": order, "is_active": True},
        )


def remove_seeded_assessment_aspects(apps, schema_editor):
    AssessmentAspect = apps.get_model("siwak", "AssessmentAspect")
    AssessmentAspect.objects.filter(
        nama__in=("Keaktifan", "Pemahaman Materi", "Kehadiran")
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("siwak", "0005_alter_eventrsvp_status_kehadiran"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AssessmentAspect",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("nama", models.CharField(max_length=100, unique=True)),
                ("urutan", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "Aspek Penilaian",
                "verbose_name_plural": "Aspek Penilaian",
                "ordering": ["urutan", "nama"],
            },
        ),
        migrations.AddField(
            model_name="mentor",
            name="npm",
            field=models.CharField(
                blank=True,
                help_text="Dipakai untuk menghubungkan data mentor dengan akun SSO UI.",
                max_length=20,
                null=True,
                unique=True,
                verbose_name="NPM",
            ),
        ),
        migrations.AddField(
            model_name="mentor",
            name="user",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="mentor_profile",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name="AssignmentReview",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "score",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                        verbose_name="Nilai Tugas",
                    ),
                ),
                ("feedback", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "reviewer",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assignment_reviews",
                        to="siwak.mentor",
                    ),
                ),
                (
                    "submission",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mentor_review",
                        to="siwak.tugassubmission",
                    ),
                ),
            ],
            options={
                "verbose_name": "Penilaian Tugas",
                "verbose_name_plural": "Penilaian Tugas",
            },
        ),
        migrations.CreateModel(
            name="AssignmentReviewHistory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "score",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                        verbose_name="Nilai Tugas",
                    ),
                ),
                ("feedback", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "reviewer",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assignment_review_history",
                        to="siwak.mentor",
                    ),
                ),
                (
                    "submission",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mentor_review_history",
                        to="siwak.tugassubmission",
                    ),
                ),
            ],
            options={
                "verbose_name": "Riwayat Penilaian Tugas",
                "verbose_name_plural": "Riwayat Penilaian Tugas",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="MentoringSession",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("judul", models.CharField(max_length=200, verbose_name="Nama/Sesi Mentoring")),
                ("tanggal", models.DateField(verbose_name="Tanggal Mentoring")),
                ("catatan", models.TextField(blank=True, verbose_name="Catatan Sesi")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "kelompok",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mentoring_sessions",
                        to="siwak.kelompokmentoring",
                    ),
                ),
            ],
            options={
                "verbose_name": "Sesi Mentoring",
                "verbose_name_plural": "Sesi Mentoring",
                "ordering": ["-tanggal", "-id"],
            },
        ),
        migrations.CreateModel(
            name="MentorFeedback",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("isi", models.TextField(verbose_name="Feedback")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "mentor",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="feedback_entries",
                        to="siwak.mentor",
                    ),
                ),
                (
                    "peserta",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mentor_feedback",
                        to="siwak.pesertamentoring",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mentee_feedback",
                        to="siwak.mentoringsession",
                    ),
                ),
            ],
            options={
                "verbose_name": "Feedback Mentor",
                "verbose_name_plural": "Feedback Mentor",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="MenteeAssessment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "score",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                        verbose_name="Nilai",
                    ),
                ),
                ("catatan", models.TextField(blank=True, verbose_name="Catatan Mentor")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "aspect",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="mentee_assessments",
                        to="siwak.assessmentaspect",
                    ),
                ),
                (
                    "assessed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mentee_assessments",
                        to="siwak.mentor",
                    ),
                ),
                (
                    "peserta",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assessments",
                        to="siwak.pesertamentoring",
                    ),
                ),
            ],
            options={
                "verbose_name": "Penilaian Mentee",
                "verbose_name_plural": "Penilaian Mentee",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("peserta", "aspect"),
                        name="unique_assessment_per_participant_aspect",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="MentoringAttendance",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("hadir", "Hadir"),
                            ("tidak_hadir", "Tidak Hadir"),
                            ("izin", "Izin"),
                        ],
                        max_length=20,
                    ),
                ),
                ("catatan", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "peserta",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mentoring_attendance",
                        to="siwak.pesertamentoring",
                    ),
                ),
                (
                    "recorded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="recorded_attendance",
                        to="siwak.mentor",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attendance_records",
                        to="siwak.mentoringsession",
                    ),
                ),
            ],
            options={
                "verbose_name": "Presensi Mentee",
                "verbose_name_plural": "Presensi Mentee",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("session", "peserta"),
                        name="unique_attendance_per_session_participant",
                    )
                ],
            },
        ),
        migrations.RunPython(
            seed_assessment_aspects,
            remove_seeded_assessment_aspects,
        ),
    ]
