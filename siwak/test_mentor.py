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
    MabaProfile,
    MenteeAssessment,
    MentoringAttendance,
    MentoringSession,
    Mentor,
    MentorFeedback,
    PesertaMentoring,
    Tugas,
    TugasSubmission,
)
from .sso import sync_maba_profile


User = get_user_model()


class MentorFeatureTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_root = tempfile.mkdtemp(prefix="web-fuki-mentor-tests-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.mentor_user = User.objects.create_user(username="2100000001")
        self.other_mentor_user = User.objects.create_user(username="2100000002")
        self.mentee_user = User.objects.create_user(username="2500000001")
        self.other_mentee_user = User.objects.create_user(username="2500000002")
        self.outsider = User.objects.create_user(username="2500000003")

        self.mentor = Mentor.objects.create(
            nama="Mentor Utama",
            npm="2100000001",
            user=self.mentor_user,
        )
        self.other_mentor = Mentor.objects.create(
            nama="Mentor Lain",
            npm="2100000002",
            user=self.other_mentor_user,
        )

        self.group = KelompokMentoring.objects.create(nama_kelompok="Kelompok A")
        self.other_group = KelompokMentoring.objects.create(nama_kelompok="Kelompok B")
        self.mentor.kelompok = self.group
        self.mentor.save(update_fields=["kelompok"])
        self.other_mentor.kelompok = self.other_group
        self.other_mentor.save(update_fields=["kelompok"])

        self.mentee_profile = MabaProfile.objects.create(
            user=self.mentee_user,
            nama_lengkap="Mentee A",
            npm="2500000001",
            jurusan="IK",
            angkatan="2025",
        )
        self.other_mentee_profile = MabaProfile.objects.create(
            user=self.other_mentee_user,
            nama_lengkap="Mentee B",
            npm="2500000002",
            jurusan="SI",
            angkatan="2025",
        )
        self.participant = PesertaMentoring.objects.create(
            maba=self.mentee_profile,
            kelompok=self.group,
        )
        self.other_participant = PesertaMentoring.objects.create(
            maba=self.other_mentee_profile,
            kelompok=self.other_group,
        )
        self.session = self.group.mentoring_sessions.get(nomor=1)
        self.session.tanggal = timezone.localdate()
        self.session.is_active = True
        self.session.save(update_fields=["tanggal", "is_active"])
        self.other_session = self.other_group.mentoring_sessions.get(nomor=1)
        self.other_session.tanggal = timezone.localdate()
        self.other_session.is_active = True
        self.other_session.save(update_fields=["tanggal", "is_active"])
        self.task = Tugas.objects.create(
            judul_tugas="Tugas Global",
            deskripsi="Kerjakan refleksi.",
            deadline=timezone.now() + datetime.timedelta(days=1),
        )
        self.submission = TugasSubmission.objects.create(
            tugas=self.task,
            user=self.mentee_user,
            file=SimpleUploadedFile("jawaban.pdf", b"test answer", content_type="application/pdf"),
        )
        self.other_submission = TugasSubmission.objects.create(
            tugas=self.task,
            user=self.other_mentee_user,
            file=SimpleUploadedFile("jawaban-lain.pdf", b"other answer", content_type="application/pdf"),
        )

    def test_non_mentor_cannot_open_mentor_dashboard(self):
        self.client.force_login(self.mentee_user)

        response = self.client.get(reverse("siwak:mentor_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_dashboard_only_lists_assigned_groups(self):
        self.client.force_login(self.mentor_user)

        response = self.client.get(reverse("siwak:mentor_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kelompok A")
        self.assertContains(response, "Mentee A")
        self.assertContains(
            response,
            reverse(
                "siwak:mentor_mentee_detail",
                kwargs={"participant_id": self.participant.pk},
            ),
        )
        self.assertNotContains(response, "Kelompok B")

    def test_group_always_has_four_fixed_sessions(self):
        sessions = self.group.mentoring_sessions.order_by("nomor")

        self.assertEqual(sessions.count(), 4)
        self.assertEqual(list(sessions.values_list("nomor", flat=True)), [1, 2, 3, 4])
        self.assertEqual(
            list(sessions.values_list("judul", flat=True)),
            [
                "Sesi Mentoring 1",
                "Sesi Mentoring 2",
                "Sesi Mentoring 3",
                "Sesi Mentoring 4",
            ],
        )

    def test_inactive_session_cannot_be_filled_by_mentor(self):
        self.client.force_login(self.mentor_user)
        inactive_session = self.group.mentoring_sessions.get(nomor=2)
        url = reverse(
            "siwak:mentor_mentee_detail",
            kwargs={"participant_id": self.participant.pk},
        )

        response = self.client.post(
            url,
            {
                "action": "session_record",
                "session_id": inactive_session.pk,
                f"session_{inactive_session.pk}-status": "hadir",
                f"session_{inactive_session.pk}-catatan": "Tidak boleh tersimpan",
                f"session_{inactive_session.pk}-feedback": "",
            },
        )
        self.assertEqual(response.status_code, 404)

        inactive_session.is_active = True
        inactive_session.save(update_fields=["is_active"])
        response = self.client.post(
            url,
            {
                "action": "session_record",
                "session_id": inactive_session.pk,
                f"session_{inactive_session.pk}-status": "hadir",
                f"session_{inactive_session.pk}-catatan": "Sudah aktif",
                f"session_{inactive_session.pk}-feedback": "",
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_mentee_detail_is_group_scoped_and_saves_assessment(self):
        self.client.force_login(self.mentor_user)
        own_url = reverse(
            "siwak:mentor_mentee_detail",
            kwargs={"participant_id": self.participant.pk},
        )
        other_url = reverse(
            "siwak:mentor_mentee_detail",
            kwargs={"participant_id": self.other_participant.pk},
        )

        self.assertEqual(self.client.get(other_url).status_code, 404)
        response = self.client.get(own_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nilai Mentee")
        self.assertContains(response, "Tugas Global")
        for number in range(1, 5):
            self.assertContains(response, f"Sesi Mentoring {number}")
        self.assertContains(response, "Status presensi")
        self.assertContains(response, "Menunggu aktivasi admin SIWAK")
        self.assertNotContains(response, "Riwayat Presensi")
        self.assertNotContains(response, "Feedback Terbaru")

        aspects = list(AssessmentAspect.objects.filter(is_active=True))
        payload = {}
        payload["action"] = "assessment"
        for aspect in aspects:
            payload[f"score_{aspect.pk}"] = 88
            payload[f"catatan_{aspect.pk}"] = "Perkembangan baik"

        response = self.client.post(own_url, payload)

        self.assertRedirects(response, f"{own_url}#penilaian")
        self.assertEqual(
            MenteeAssessment.objects.filter(peserta=self.participant, score=88).count(),
            len(aspects),
        )

    def test_mentor_cannot_access_another_mentors_session(self):
        self.client.force_login(self.mentor_user)

        response = self.client.post(
            reverse(
                "siwak:mentor_mentee_detail",
                kwargs={"participant_id": self.participant.pk},
            ),
            {
                "action": "session_record",
                "session_id": self.other_session.pk,
                f"session_{self.other_session.pk}-status": "hadir",
                f"session_{self.other_session.pk}-catatan": "",
                f"session_{self.other_session.pk}-feedback": "",
            },
        )

        self.assertEqual(response.status_code, 404)

    def test_session_card_updates_one_attendance_record_for_mentee(self):
        self.client.force_login(self.mentor_user)
        detail_url = reverse(
            "siwak:mentor_mentee_detail",
            kwargs={"participant_id": self.participant.pk},
        )

        response = self.client.post(
            detail_url,
            {
                "action": "session_record",
                "session_id": self.session.pk,
                f"session_{self.session.pk}-status": "hadir",
                f"session_{self.session.pk}-catatan": "Tepat waktu",
                f"session_{self.session.pk}-feedback": "",
            },
        )

        self.assertRedirects(
            response,
            f"{detail_url}#session-{self.session.pk}",
        )
        response = self.client.post(
            detail_url,
            {
                "action": "session_record",
                "session_id": self.session.pk,
                f"session_{self.session.pk}-status": "izin",
                f"session_{self.session.pk}-catatan": "Sakit",
                f"session_{self.session.pk}-feedback": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            MentoringAttendance.objects.filter(
                session=self.session,
                peserta=self.participant,
            ).count(),
            1,
        )
        attendance = MentoringAttendance.objects.get(
            session=self.session,
            peserta=self.participant,
        )
        self.assertEqual(attendance.status, "izin")
        self.assertEqual(attendance.recorded_by, self.mentor)

    def test_assessment_rejects_score_above_100_and_saves_valid_score(self):
        aspect = AssessmentAspect.objects.get(nama="Keaktifan")
        aspects = list(AssessmentAspect.objects.filter(is_active=True))
        self.client.force_login(self.mentor_user)
        url = reverse(
            "siwak:mentor_mentee_detail",
            kwargs={"participant_id": self.participant.pk},
        )
        invalid_payload = {}
        invalid_payload["action"] = "assessment"
        for item in aspects:
            invalid_payload[f"score_{item.pk}"] = 101 if item == aspect else ""
            invalid_payload[f"catatan_{item.pk}"] = ""

        response = self.client.post(url, invalid_payload)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(MenteeAssessment.objects.exists())

        valid_payload = {}
        valid_payload["action"] = "assessment"
        for item in aspects:
            valid_payload[f"score_{item.pk}"] = 85 if item == aspect else ""
            valid_payload[f"catatan_{item.pk}"] = "Aktif berdiskusi" if item == aspect else ""
        response = self.client.post(url, valid_payload)

        self.assertEqual(response.status_code, 302)
        assessment = MenteeAssessment.objects.get(peserta=self.participant, aspect=aspect)
        self.assertEqual(assessment.score, 85)
        self.assertEqual(assessment.assessed_by, self.mentor)

    def test_assignment_page_only_contains_current_groups_mentees(self):
        self.client.force_login(self.mentor_user)

        response = self.client.get(
            reverse("siwak:mentor_assignments", kwargs={"group_id": self.group.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mentee A")
        self.assertNotContains(response, "Mentee B")

    def test_assignment_review_is_group_scoped_and_records_reviewer(self):
        self.client.force_login(self.mentor_user)
        detail_url = reverse(
            "siwak:mentor_mentee_detail",
            kwargs={"participant_id": self.participant.pk},
        )

        response = self.client.post(
            detail_url,
            {
                "action": "assignment_review",
                "submission_id": self.other_submission.pk,
                f"assignment_{self.other_submission.pk}-score": 92,
                f"assignment_{self.other_submission.pk}-feedback": "Tidak boleh tersimpan.",
            },
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.post(
            detail_url,
            {
                "action": "assignment_review",
                "submission_id": self.submission.pk,
                f"assignment_{self.submission.pk}-score": 92,
                f"assignment_{self.submission.pk}-feedback": "Bagus.",
            },
        )

        self.assertEqual(response.status_code, 302)
        review = AssignmentReview.objects.get(submission=self.submission)
        self.assertEqual(review.score, 92)
        self.assertEqual(review.reviewer, self.mentor)
        self.assertTrue(
            AssignmentReviewHistory.objects.filter(
                submission=self.submission,
                score=92,
                reviewer=self.mentor,
            ).exists()
        )

    def test_submission_download_allows_owner_and_responsible_mentor_only(self):
        url = reverse("siwak:submission_download", kwargs={"submission_id": self.submission.pk})

        self.client.force_login(self.mentee_user)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.mentor_user)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_submission_file_is_not_public_through_media_url(self):
        self.client.force_login(self.mentee_user)

        response = self.client.get(self.submission.file.url)

        self.assertEqual(response.status_code, 404)

    def test_session_feedback_is_visible_only_to_related_mentee(self):
        self.client.force_login(self.mentor_user)
        feedback_url = reverse(
            "siwak:mentor_mentee_detail",
            kwargs={"participant_id": self.participant.pk},
        )

        response = self.client.post(
            feedback_url,
            {
                "action": "session_record",
                "session_id": self.session.pk,
                f"session_{self.session.pk}-status": "hadir",
                f"session_{self.session.pk}-catatan": "",
                f"session_{self.session.pk}-feedback": "Perkembangan sangat baik.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            MentorFeedback.objects.filter(
                session=self.session,
                peserta=self.participant,
                mentor=self.mentor,
            ).exists()
        )

        self.client.force_login(self.mentee_user)
        response = self.client.get(reverse("siwak:mentee_feedback_history"))
        self.assertContains(response, "Perkembangan sangat baik.")

        self.client.force_login(self.other_mentee_user)
        response = self.client.get(reverse("siwak:mentee_feedback_history"))
        self.assertNotContains(response, "Perkembangan sangat baik.")

    def test_seeded_mentor_is_linked_on_matching_sso_profile_sync(self):
        unlinked_user = User.objects.create_user(username="2100000009")
        unlinked_mentor = Mentor.objects.create(nama="Mentor Seed", npm="2100000009")

        sync_maba_profile(
            user=unlinked_user,
            npm="2100000009",
            nama_lengkap="Mentor Seed",
            jurusan="IK",
            angkatan="2021",
        )

        unlinked_mentor.refresh_from_db()
        self.assertEqual(unlinked_mentor.user, unlinked_user)
