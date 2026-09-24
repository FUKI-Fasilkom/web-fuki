"""Pengawasan pengurus atas data mentoring yang diisi mentor di panel SIWAK."""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Answer,
    AssessmentAspect,
    AssignmentReview,
    AssignmentReviewHistory,
    KelompokMentoring,
    MenteeAssessment,
    MentorFeedback,
    MentoringAttendance,
    Profile,
    Question,
    Tugas,
    TugasSubmission,
)


User = get_user_model()

def _profil(username, nama, role, kelompok=None, npm=None, **extra):
    return Profile.objects.create(
        user=User.objects.create_user(username=username, **extra),
        npm=npm or username,
        nama_lengkap=nama,
        jurusan="IK",
        role=role,
        kelompok=kelompok,
    )


class PengawasanAdminTests(TestCase):
    """Staff can inspect everything mentors recorded, per mentee and per group."""

    def setUp(self):
        self.staf = User.objects.create_user(username="pengurus", is_staff=True)
        self.kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok 7")
        self.mentor = _profil("2100000070", "Kak Ahmad", Profile.ROLE_MENTOR, self.kelompok)
        self.mentee = _profil("2500000070", "Aisyah Putri", Profile.ROLE_MENTEE, self.kelompok)
        self.teman = _profil("2500000071", "Bima Sakti", Profile.ROLE_MENTEE, self.kelompok)

        sesi1 = self.kelompok.mentoring_sessions.get(nomor=1)
        MentoringAttendance.objects.create(
            session=sesi1, peserta=self.mentee, status="hadir", catatan="Datang awal",
            recorded_by=self.mentor,
        )
        MentorFeedback.objects.create(
            session=sesi1, peserta=self.mentee, mentor=self.mentor, isi="Aktif berdiskusi."
        )
        self.aspek = AssessmentAspect.objects.create(nama="Akhlak", urutan=1)
        MenteeAssessment.objects.create(
            peserta=self.mentee, aspect=self.aspek, score=88, catatan="Sopan", assessed_by=self.mentor
        )
        MenteeAssessment.objects.create(
            peserta=self.teman, aspect=self.aspek, score=70, assessed_by=self.mentor
        )

        self.tugas = Tugas.objects.create(
            judul_tugas="Refleksi Pekan 1", deskripsi="d",
            deadline=timezone.now() + datetime.timedelta(days=1),
        )
        soal = Question.objects.create(tugas=self.tugas, pertanyaan="Apa yang kamu pelajari?", tipe="text")
        submission = TugasSubmission.objects.create(tugas=self.tugas, user=self.mentee.user)
        Answer.objects.create(submission=submission, question=soal, text_answer="Sabar itu penting.")
        AssignmentReview.objects.create(
            submission=submission, score=92, feedback="Refleksi yang jujur.", reviewer=self.mentor
        )
        AssignmentReviewHistory.objects.create(
            submission=submission, score=80, feedback="Coba lebih dalam.", reviewer=self.mentor
        )
        AssignmentReviewHistory.objects.create(
            submission=submission, score=92, feedback="Refleksi yang jujur.", reviewer=self.mentor
        )
        self.url = reverse("siwak:panel_mentee_detail", args=[self.mentee.pk])

    def test_the_mentee_page_shows_everything_the_mentor_recorded(self):
        self.client.force_login(self.staf)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        for teks in (
            # presensi & feedback sesi
            "Hadir", "Datang awal", "Aktif berdiskusi.",
            # nilai per aspek
            "Akhlak", "88", "Sopan",
            # tugas: jawaban, nilai, feedback, riwayat
            "Refleksi Pekan 1", "Sabar itu penting.", "Nilai 92", "Refleksi yang jujur.",
            "Coba lebih dalam.",
        ):
            with self.subTest(teks=teks):
                self.assertContains(response, teks)
        self.assertContains(response, "Kak Ahmad")
        self.assertEqual(response.context["rata_nilai"], 88)
        self.assertEqual((response.context["jumlah_terkumpul"], response.context["jumlah_dinilai"]), (1, 1))

    def test_the_mentee_page_is_staff_only(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

        for akun in (self.mentor.user, self.mentee.user):
            with self.subTest(username=akun.username):
                self.client.force_login(akun)
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_only_mentees_have_this_page(self):
        self.client.force_login(self.staf)

        response = self.client.get(reverse("siwak:panel_mentee_detail", args=[self.mentor.pk]))

        self.assertEqual(response.status_code, 404)

    def test_the_group_page_summarises_grades_and_reviews_and_links_each_mentee(self):
        self.client.force_login(self.staf)

        response = self.client.get(reverse("siwak:panel_kelompok_detail", args=[self.kelompok.pk]))

        aisyah, bima = response.context["baris"]
        self.assertEqual((aisyah["rata_nilai"], aisyah["tugas"], aisyah["dinilai"]), (88, 1, 1))
        self.assertEqual((bima["rata_nilai"], bima["tugas"], bima["dinilai"]), (70, 0, 0))
        self.assertContains(response, f'href="{self.url}"')

    def test_the_mentee_list_links_to_the_mentee_page(self):
        self.client.force_login(self.staf)

        response = self.client.get(reverse("siwak:panel_daftar", args=["peserta"]))

        self.assertContains(response, f'href="{self.url}"')

    def test_the_attendance_list_shows_every_record_with_its_feedback(self):
        self.client.force_login(self.staf)

        response = self.client.get(reverse("siwak:panel_daftar", args=["presensi"]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aisyah Putri")
        self.assertContains(response, "Aktif berdiskusi.")
        self.assertContains(response, "Datang awal")
        self.assertContains(response, f'href="{self.url}"')
        # Hanya baca: presensi diisi mentor dari portalnya.
        self.assertEqual(
            self.client.get(reverse("siwak:panel_tambah", args=["presensi"])).status_code, 404
        )
