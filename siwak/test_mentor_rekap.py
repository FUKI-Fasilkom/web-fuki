import datetime
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    AssignmentReview,
    AssignmentReviewHistory,
    AssessmentAspect,
    KelompokMentoring,
    MahasiswaProfile,
    MenteeAssessment,
    MentoringAttendance,
    MentorFeedback,
    Tugas,
    TugasSubmission,
)


User = get_user_model()


class MentorRekapPagesTests(TestCase):
    """Presensi Mentoring, Nilai Mentee, dan Penilaian Tugas."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_root = tempfile.mkdtemp(prefix="web-fuki-rekap-tests-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()

    def _profile(self, npm, nama, role=MahasiswaProfile.ROLE_MENTEE, kelompok=None):
        user = User.objects.create_user(username=npm)
        return MahasiswaProfile.objects.create(
            user=user, npm=npm, nama_lengkap=nama, jurusan="IK", role=role, kelompok=kelompok
        )

    def setUp(self):
        self.group = KelompokMentoring.objects.create(nama_kelompok="Kelompok A")
        self.other_group = KelompokMentoring.objects.create(nama_kelompok="Kelompok B")
        self.mentor = self._profile("2100000001", "Mentor Utama", MahasiswaProfile.ROLE_MENTOR, self.group)
        self.other_mentor = self._profile(
            "2100000002", "Mentor Lain", MahasiswaProfile.ROLE_MENTOR, self.other_group
        )
        self.ani = self._profile("2500000001", "Ani Mentee", kelompok=self.group)
        self.budi = self._profile("2500000002", "Budi Mentee", kelompok=self.group)
        self.outsider = self._profile("2500000003", "Orang Luar", kelompok=self.other_group)

        for nomor in (1, 2):
            self.group.mentoring_sessions.filter(nomor=nomor).update(is_active=True)
        self.sesi1 = self.group.mentoring_sessions.get(nomor=1)
        self.sesi2 = self.group.mentoring_sessions.get(nomor=2)
        self.sesi3 = self.group.mentoring_sessions.get(nomor=3)  # tidak aktif

        self.aspect_a = AssessmentAspect.objects.create(nama="Akhlak", urutan=1)
        self.aspect_b = AssessmentAspect.objects.create(nama="Tilawah", urutan=2)

        self.task = Tugas.objects.create(
            judul_tugas="Refleksi Pekan 1",
            deskripsi="x",
            deadline=timezone.now() + datetime.timedelta(days=1),
        )
        self.sub_ani = self._submit(self.task, self.ani)
        self.sub_outsider = self._submit(self.task, self.outsider)

    def _submit(self, task, profile):
        return TugasSubmission.objects.create(
            tugas=task,
            user=profile.user,
            file=SimpleUploadedFile("j.pdf", b"x", content_type="application/pdf"),
        )

    def test_dashboard_buttons_precede_daftar_mentee_in_order(self):
        self.client.force_login(self.mentor.user)
        html = self.client.get(reverse("siwak:mentor_dashboard")).content.decode()

        positions = [
            html.index("Presensi Mentoring"),
            html.index("Nilai Mentee"),
            html.index("Penilaian Tugas"),
            html.index("Daftar Mentee"),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_pages_are_mentor_only(self):
        self.client.force_login(self.ani.user)
        for name in ("mentor_attendance", "mentor_assessments", "mentor_task_reviews"):
            self.assertEqual(self.client.get(reverse(f"siwak:{name}")).status_code, 403, name)

    def test_attendance_page_is_group_scoped_and_filterable(self):
        self.client.force_login(self.mentor.user)
        url = reverse("siwak:mentor_attendance")

        response = self.client.get(url)
        self.assertContains(response, "Ani Mentee")
        self.assertContains(response, "Budi Mentee")
        self.assertNotContains(response, "Orang Luar")

        response = self.client.get(url, {"sesi": "2", "q": "budi"})
        self.assertContains(response, "Budi Mentee")
        self.assertNotContains(response, "Ani Mentee")
        self.assertContains(response, "Sesi Mentoring 2")
        self.assertEqual(
            {row["session"].nomor for row in response.context["halaman"].object_list}, {2}
        )

    def _attendance_post(self, session, participant, **fields):
        prefix = f"s{session.pk}m{participant.pk}"
        return {f"{prefix}-{key}": value for key, value in fields.items()}

    def test_attendance_saves_and_edits_status_note_and_feedback(self):
        self.client.force_login(self.mentor.user)
        url = reverse("siwak:mentor_attendance")
        data = self._attendance_post(
            self.sesi1, self.ani, status="hadir", catatan="Tepat waktu", feedback="Aktif bertanya."
        )
        # Baris lain dikirim kosong dan tidak boleh menghasilkan apa pun.
        data.update(self._attendance_post(self.sesi1, self.budi, status="", catatan="", feedback=""))

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302)
        attendance = MentoringAttendance.objects.get(session=self.sesi1, peserta=self.ani)
        self.assertEqual((attendance.status, attendance.catatan), ("hadir", "Tepat waktu"))
        self.assertEqual(attendance.recorded_by, self.mentor)
        self.assertEqual(MentoringAttendance.objects.count(), 1)
        feedback = MentorFeedback.objects.get(session=self.sesi1, peserta=self.ani)
        self.assertEqual(feedback.isi, "Aktif bertanya.")

        # Refresh: nilai tampil lagi, lalu disunting -> feedback yang sama diperbarui.
        self.assertContains(self.client.get(url), "Aktif bertanya.")
        data = self._attendance_post(
            self.sesi1, self.ani, status="izin", catatan="Sakit", feedback="Semoga lekas sembuh."
        )
        self.client.post(url, data)
        attendance.refresh_from_db()
        self.assertEqual(attendance.status, "izin")
        self.assertEqual(MentorFeedback.objects.filter(peserta=self.ani).count(), 1)
        self.assertEqual(MentorFeedback.objects.get(peserta=self.ani).isi, "Semoga lekas sembuh.")

        # Mengosongkan feedback menghapusnya; presensi tetap ada.
        self.client.post(
            url, self._attendance_post(self.sesi1, self.ani, status="izin", catatan="Sakit", feedback="")
        )
        self.assertFalse(MentorFeedback.objects.filter(peserta=self.ani).exists())
        self.assertTrue(MentoringAttendance.objects.filter(peserta=self.ani).exists())

    def test_attendance_invalid_row_blocks_the_whole_save(self):
        self.client.force_login(self.mentor.user)
        data = self._attendance_post(self.sesi1, self.ani, status="hadir", catatan="", feedback="")
        # Feedback tanpa status = baris tidak valid.
        data.update(self._attendance_post(self.sesi1, self.budi, status="", catatan="", feedback="Tanpa status"))

        response = self.client.post(reverse("siwak:mentor_attendance"), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "belum valid")
        self.assertContains(response, "Tanpa status")  # isian tidak hilang
        self.assertFalse(MentoringAttendance.objects.exists())

    def test_attendance_inactive_session_and_foreign_rows_are_ignored(self):
        self.client.force_login(self.mentor.user)
        outsider_session = self.other_group.mentoring_sessions.get(nomor=1)
        outsider_session.is_active = True
        outsider_session.save(update_fields=["is_active"])
        data = self._attendance_post(self.sesi3, self.ani, status="hadir", catatan="", feedback="")
        data.update(self._attendance_post(outsider_session, self.outsider, status="hadir", catatan="", feedback=""))

        self.client.post(reverse("siwak:mentor_attendance"), data)

        self.assertFalse(MentoringAttendance.objects.exists())

    def test_assessment_page_renders_every_aspect_dynamically(self):
        AssessmentAspect.objects.create(nama="Kedisiplinan", urutan=3)
        self.client.force_login(self.mentor.user)

        response = self.client.get(reverse("siwak:mentor_assessments"))

        for nama in ("Akhlak", "Tilawah", "Kedisiplinan"):
            self.assertContains(response, nama)
        self.assertContains(response, "Ani Mentee")
        self.assertNotContains(response, "Orang Luar")
        total = AssessmentAspect.objects.filter(is_active=True).count()
        self.assertGreaterEqual(total, 3)
        self.assertEqual(response.content.decode().count(">Nilai</th>"), total)
        self.assertEqual(response.content.decode().count(">Catatan</th>"), total)

    def _assessment_post(self, participant, **fields):
        return {f"m{participant.pk}-{key}": value for key, value in fields.items()}

    def test_assessment_creates_updates_and_preserves_existing_data(self):
        self.client.force_login(self.mentor.user)
        url = reverse("siwak:mentor_assessments")
        data = self._assessment_post(
            self.ani,
            **{
                f"score_{self.aspect_a.pk}": 80,
                f"catatan_{self.aspect_a.pk}": "Baik",
                f"score_{self.aspect_b.pk}": "",
                f"catatan_{self.aspect_b.pk}": "",
            },
        )
        self.assertEqual(self.client.post(url, data).status_code, 302)
        row = MenteeAssessment.objects.get(peserta=self.ani, aspect=self.aspect_a)
        self.assertEqual((row.score, row.catatan, row.assessed_by), (80, "Baik", self.mentor))
        self.assertFalse(MenteeAssessment.objects.filter(aspect=self.aspect_b).exists())

        # Halaman memuat ulang nilai tersimpan sebagai isian awal.
        self.assertContains(self.client.get(url), 'value="80"')

        data = self._assessment_post(
            self.ani,
            **{
                f"score_{self.aspect_a.pk}": 90,
                f"catatan_{self.aspect_a.pk}": "Sangat baik",
                f"score_{self.aspect_b.pk}": 70,
                f"catatan_{self.aspect_b.pk}": "",
            },
        )
        self.client.post(url, data)
        self.assertEqual(MenteeAssessment.objects.filter(peserta=self.ani).count(), 2)
        row.refresh_from_db()
        self.assertEqual((row.score, row.catatan), (90, "Sangat baik"))

    def test_assessment_rejects_out_of_range_and_note_without_score(self):
        self.client.force_login(self.mentor.user)
        url = reverse("siwak:mentor_assessments")
        data = self._assessment_post(
            self.ani,
            **{
                f"score_{self.aspect_a.pk}": 101,
                f"catatan_{self.aspect_a.pk}": "",
                f"score_{self.aspect_b.pk}": "",
                f"catatan_{self.aspect_b.pk}": "Catatan tanpa nilai",
            },
        )
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "belum valid")
        self.assertFalse(MenteeAssessment.objects.exists())

    def test_assessment_search_filters_mentees(self):
        self.client.force_login(self.mentor.user)
        response = self.client.get(reverse("siwak:mentor_assessments"), {"q": "budi"})
        self.assertContains(response, "Budi Mentee")
        self.assertNotContains(response, "Ani Mentee")

    def test_task_review_page_only_lists_own_groups_submissions(self):
        self.client.force_login(self.mentor.user)
        url = reverse("siwak:mentor_task_reviews")

        response = self.client.get(url)
        self.assertContains(response, "Ani Mentee")
        self.assertContains(response, "Refleksi Pekan 1")
        self.assertNotContains(response, "Orang Luar")
        self.assertContains(
            response,
            reverse("siwak:submission_download", kwargs={"submission_id": self.sub_ani.pk}),
        )
        self.assertNotContains(response, "Budi Mentee")  # belum mengumpulkan

        self.assertContains(self.client.get(url, {"q": "zzz"}), "Tidak ada submission")
        self.assertNotContains(self.client.get(url, {"status": "sudah"}), "Ani Mentee")

    def test_task_review_saves_score_feedback_and_history(self):
        self.client.force_login(self.mentor.user)
        url = reverse("siwak:mentor_task_reviews")
        prefix = f"t{self.sub_ani.pk}"

        self.assertEqual(
            self.client.post(url, {f"{prefix}-score": 88, f"{prefix}-feedback": "Rapi."}).status_code, 302
        )
        review = AssignmentReview.objects.get(submission=self.sub_ani)
        self.assertEqual((review.score, review.feedback, review.reviewer), (88, "Rapi.", self.mentor))

        # Sunting: satu review, riwayat bertambah; submit ulang tanpa perubahan tidak menambah riwayat.
        self.client.post(url, {f"{prefix}-score": 95, f"{prefix}-feedback": "Sempurna."})
        self.client.post(url, {f"{prefix}-score": 95, f"{prefix}-feedback": "Sempurna."})
        self.assertEqual(AssignmentReview.objects.filter(submission=self.sub_ani).count(), 1)
        self.assertEqual(AssignmentReviewHistory.objects.filter(submission=self.sub_ani).count(), 2)
        self.assertContains(self.client.get(url), "Sempurna.")

    def test_task_review_rejects_invalid_score_and_foreign_submission(self):
        self.client.force_login(self.mentor.user)
        url = reverse("siwak:mentor_task_reviews")
        response = self.client.post(url, {f"t{self.sub_ani.pk}-score": 150, f"t{self.sub_ani.pk}-feedback": "x"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AssignmentReview.objects.exists())

        # Submission mentee kelompok lain tidak ada di halaman ini, jadi datanya diabaikan.
        self.client.post(
            url, {f"t{self.sub_outsider.pk}-score": 50, f"t{self.sub_outsider.pk}-feedback": "x"}
        )
        self.assertFalse(AssignmentReview.objects.filter(submission=self.sub_outsider).exists())

    def test_mentor_without_group_sees_empty_state(self):
        self.mentor.kelompok = None
        self.mentor.save(update_fields=["kelompok"])
        self.client.force_login(self.mentor.user)
        for name in ("mentor_attendance", "mentor_assessments", "mentor_task_reviews"):
            response = self.client.get(reverse(f"siwak:{name}"))
            self.assertContains(response, "Kelompok belum ditetapkan")
