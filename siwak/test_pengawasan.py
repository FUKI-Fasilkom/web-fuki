"""Pengawasan pengurus atas data mentoring, catatan privat mentee, dan
penyaring kelompok/sesi di panel SIWAK.

Regression guard yang paling penting di sini: `Profile.notes` hanya boleh
terbaca dan tersunting oleh pengurus dan mentor kelompok mentee itu — tidak
pernah oleh mentee sendiri, mentee lain, mentor kelompok lain, atau pengunjung.
"""

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
    EventRSVP,
    KelompokMentoring,
    MenteeAssessment,
    MentorFeedback,
    MentoringAttendance,
    Profile,
    Question,
    SiwakEvent,
    Tugas,
    TugasSubmission,
)
from .services.mentor import boleh_akses_catatan
from .services.qrcode_service import sign_payload


User = get_user_model()

CATATAN = "Perlu pendampingan ekstra soal tilawah."


def _profil(username, nama, role, kelompok=None, npm=None, **extra):
    return Profile.objects.create(
        user=User.objects.create_user(username=username, **extra),
        npm=npm or username,
        nama_lengkap=nama,
        jurusan="IK",
        role=role,
        kelompok=kelompok,
    )


class CatatanMenteeTests(TestCase):
    """Who may read and write the private note on one mentee."""

    def setUp(self):
        self.kelompok_a = KelompokMentoring.objects.create(nama_kelompok="Kelompok A")
        self.kelompok_b = KelompokMentoring.objects.create(nama_kelompok="Kelompok B")
        self.mentor_a = _profil("2100000001", "Mentor A", Profile.ROLE_MENTOR, self.kelompok_a)
        self.mentor_b = _profil("2100000002", "Mentor B", Profile.ROLE_MENTOR, self.kelompok_b)
        self.mentee_a = _profil("2500000001", "Mentee A", Profile.ROLE_MENTEE, self.kelompok_a)
        self.teman_a = _profil("2500000002", "Teman A", Profile.ROLE_MENTEE, self.kelompok_a)
        self.mentee_a.notes = CATATAN
        self.mentee_a.save(update_fields=["notes"])
        self.staf = User.objects.create_user(username="pengurus", is_staff=True)
        self.url_simpan = reverse("siwak:mentee_catatan", args=[self.mentee_a.pk])

    def _simpan(self, isi="Catatan baru", **extra):
        return self.client.post(self.url_simpan, {"notes": isi, **extra})

    def _catatan(self):
        self.mentee_a.refresh_from_db()
        return self.mentee_a.notes

    def test_the_groups_mentor_can_read_and_write_it(self):
        self.client.force_login(self.mentor_a.user)
        halaman = reverse("siwak:mentor_mentee_detail", args=[self.mentee_a.pk])

        self.assertContains(self.client.get(halaman), CATATAN)

        response = self._simpan(next=f"{halaman}#catatan")

        self.assertRedirects(response, f"{halaman}#catatan", fetch_redirect_response=False)
        self.assertEqual(self._catatan(), "Catatan baru")

    def test_staff_can_read_and_write_it(self):
        self.client.force_login(self.staf)

        self.assertContains(
            self.client.get(reverse("siwak:panel_mentee_detail", args=[self.mentee_a.pk])), CATATAN
        )
        self.assertContains(
            self.client.get(reverse("siwak:panel_kelompok_detail", args=[self.kelompok_a.pk])), CATATAN
        )

        response = self._simpan()

        self.assertRedirects(
            response, reverse("siwak:panel_mentee_detail", args=[self.mentee_a.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(self._catatan(), "Catatan baru")

    def test_a_mentor_of_another_group_gets_403_and_never_sees_it(self):
        self.client.force_login(self.mentor_b.user)

        self.assertEqual(self._simpan().status_code, 403)
        self.assertEqual(self._catatan(), CATATAN)
        # Halaman mentee kelompok lain memang tertutup untuknya.
        response = self.client.get(reverse("siwak:mentor_mentee_detail", args=[self.mentee_a.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, CATATAN, status_code=404)

    def test_the_mentee_and_other_mentees_can_neither_read_nor_write_it(self):
        for mentee in (self.mentee_a, self.teman_a):
            with self.subTest(mentee=mentee.nama_lengkap):
                self.client.force_login(mentee.user)
                self.assertEqual(self._simpan().status_code, 403)
                for url in (
                    reverse("siwak:tugas_list"),
                    reverse("siwak:mentee_feedback_history"),
                    reverse("siwak:landing"),
                ):
                    self.assertNotContains(self.client.get(url), CATATAN)
                self.assertEqual(
                    self.client.get(reverse("siwak:panel_mentee_detail", args=[self.mentee_a.pk])).status_code,
                    403,
                )
        self.assertEqual(self._catatan(), CATATAN)

    def test_it_is_masked_from_clarity_session_recordings(self):
        """Second layer behind ClarityTests: these pages do not load Clarity at
        all, but the note stays masked should that ever change."""
        masker = 'data-clarity-mask="True"'
        self.client.force_login(self.mentor_a.user)
        self.assertContains(
            self.client.get(reverse("siwak:mentor_mentee_detail", args=[self.mentee_a.pk])), masker
        )
        self.client.force_login(self.staf)
        for url in (
            reverse("siwak:panel_mentee_detail", args=[self.mentee_a.pk]),
            reverse("siwak:panel_kelompok_detail", args=[self.kelompok_a.pk]),
        ):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), masker)

    def test_the_public_group_search_never_shows_it(self):
        response = self.client.post(reverse("siwak:kelompok_search"), {"nama_lengkap": "Mentee A"})

        self.assertEqual(response.context["result_state"], "found")
        self.assertNotContains(response, CATATAN)

    def test_a_mentor_without_a_group_cannot_touch_an_ungrouped_mentee(self):
        """kelompok_id=None on both sides must not count as "same group"."""
        tanpa_kelompok = _profil("2100000003", "Mentor Lepas", Profile.ROLE_MENTOR)
        mentee_lepas = _profil("2500000009", "Mentee Lepas", Profile.ROLE_MENTEE)

        self.assertFalse(boleh_akses_catatan(tanpa_kelompok.user, mentee_lepas))
        self.client.force_login(tanpa_kelompok.user)
        response = self.client.post(
            reverse("siwak:mentee_catatan", args=[mentee_lepas.pk]), {"notes": "x"}
        )
        self.assertEqual(response.status_code, 403)

    def test_only_logged_in_posts_are_accepted(self):
        response = self._simpan()
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("siwak:login"), response.url)

        self.client.force_login(self.mentor_a.user)
        self.assertEqual(self.client.get(self.url_simpan).status_code, 405)
        self.assertEqual(self._catatan(), CATATAN)

    def test_an_offsite_next_is_ignored(self):
        self.client.force_login(self.mentor_a.user)

        response = self._simpan(next="https://jahat.example.com/")

        self.assertRedirects(
            response, reverse("siwak:mentor_mentee_detail", args=[self.mentee_a.pk]),
            fetch_redirect_response=False,
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


class PanelSaringanTests(TestCase):
    """The kelompok / sesi dropdown filters on the panel lists."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="pengurus", is_staff=True))
        self.kelompok_a = KelompokMentoring.objects.create(nama_kelompok="Kelompok A")
        self.kelompok_b = KelompokMentoring.objects.create(nama_kelompok="Kelompok B")
        self.kelompok_a.mentoring_sessions.filter(nomor=1).update(is_active=True)
        self.ani = _profil("2500000001", "Ani", Profile.ROLE_MENTEE, self.kelompok_a)
        self.budi = _profil("2500000002", "Budi", Profile.ROLE_MENTEE, self.kelompok_b)
        for mentee, kelompok in ((self.ani, self.kelompok_a), (self.budi, self.kelompok_b)):
            for nomor, status in ((1, "hadir"), (2, "izin")):
                MentoringAttendance.objects.create(
                    session=kelompok.mentoring_sessions.get(nomor=nomor), peserta=mentee, status=status
                )

    def _daftar(self, slug, **params):
        response = self.client.get(reverse("siwak:panel_daftar", args=[slug]), params)
        self.assertEqual(response.status_code, 200)
        return response, list(response.context["halaman"].object_list)

    def test_the_session_list_filters_by_group_session_and_status(self):
        a = str(self.kelompok_a.pk)

        _, sesi = self._daftar("sesi", kelompok=a)
        self.assertEqual({s.kelompok_id for s in sesi}, {self.kelompok_a.pk})
        self.assertEqual(len(sesi), 4)

        _, sesi = self._daftar("sesi", kelompok=a, sesi="2")
        self.assertEqual([(s.kelompok_id, s.nomor) for s in sesi], [(self.kelompok_a.pk, 2)])

        _, sesi = self._daftar("sesi", sesi="2")
        self.assertEqual({s.kelompok_id for s in sesi}, {self.kelompok_a.pk, self.kelompok_b.pk})

        _, sesi = self._daftar("sesi", aktif="1")
        self.assertEqual([(s.kelompok_id, s.nomor) for s in sesi], [(self.kelompok_a.pk, 1)])

    def test_the_attendance_list_filters_by_group_session_and_status(self):
        _, baris = self._daftar("presensi", kelompok=str(self.kelompok_b.pk))
        self.assertEqual({b.peserta_id for b in baris}, {self.budi.pk})

        _, baris = self._daftar("presensi", sesi="2")
        self.assertEqual({(b.peserta_id, b.session.nomor) for b in baris}, {(self.ani.pk, 2), (self.budi.pk, 2)})

        _, baris = self._daftar("presensi", kelompok=str(self.kelompok_a.pk), status="hadir")
        self.assertEqual([(b.peserta_id, b.session.nomor) for b in baris], [(self.ani.pk, 1)])

    def test_the_mentee_list_filters_by_group(self):
        _, mentee = self._daftar("peserta", kelompok=str(self.kelompok_a.pk))

        self.assertEqual(mentee, [self.ani])

    def test_unknown_filter_values_are_ignored_not_queried(self):
        response, baris = self._daftar("presensi", kelompok="bukan-angka", sesi="9", status="mungkin")

        self.assertEqual(len(baris), 4)
        self.assertFalse(response.context["ada_saringan"])

    def test_filters_survive_search_sorting_and_paging(self):
        a = str(self.kelompok_a.pk)

        response, _ = self._daftar("presensi", kelompok=a, sesi="1", q="ani")

        self.assertIn(f"kelompok={a}", response.context["kueri"])
        self.assertIn("sesi=1", response.context["kueri"])
        urut = [k["url"] for k in response.context["kepala"] if k["bisa_urut"]]
        self.assertTrue(urut)
        self.assertTrue(all(f"kelompok={a}" in u and "sesi=1" in u for u in urut))
        self.assertContains(response, f'<option value="{a}" selected>Kelompok A</option>', html=True)

    def test_the_group_page_can_narrow_its_grid_to_one_session(self):
        response = self.client.get(
            reverse("siwak:panel_kelompok_detail", args=[self.kelompok_a.pk]), {"sesi": "2"}
        )

        self.assertEqual([k["sesi"].nomor for k in response.context["kolom_sesi"]], [2])
        (ani,) = response.context["baris"]
        self.assertEqual([p["status"] for p in ani["presensi"]], ["izin"])


class ClarityTests(TestCase):
    """Microsoft Clarity records sessions, page text included: it belongs on
    public pages only, never on internal pages showing other students' names
    and NPMs."""

    TAG = "clarity.ms/tag/"

    def test_public_pages_load_clarity(self):
        for url in ("/", reverse("siwak:landing"), reverse("siwak:kelompok_search"), reverse("siwak:login")):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), self.TAG)

    def test_internal_pages_do_not_load_clarity(self):
        kelompok = KelompokMentoring.objects.create(nama_kelompok="Kelompok A")
        mentor = _profil("2100000001", "Mentor A", Profile.ROLE_MENTOR, kelompok)
        mentee = _profil("2500000001", "Mentee A", Profile.ROLE_MENTEE, kelompok)
        rsvp = EventRSVP.objects.create(
            event=SiwakEvent.objects.create(judul="Main Event"), user=mentee.user
        )
        qr = reverse("siwak:qr_verify", args=[sign_payload("registrasi", rsvp.qr_registrasi_token)])

        halaman = {
            User.objects.create_superuser(username="admin", password="x"): (
                reverse("siwak:panel_beranda"),
                reverse("siwak:panel_daftar", args=["peserta"]),
                reverse("siwak:panel_kelompok_detail", args=[kelompok.pk]),
                reverse("siwak:panel_mentee_detail", args=[mentee.pk]),
                reverse("siwak:panel_rsvp", args=[rsvp.event_id]),
                reverse("siwak:pindai_beranda"),
                qr,
            ),
            mentor.user: (
                reverse("siwak:mentor_dashboard"),
                reverse("siwak:mentor_mentee_detail", args=[mentee.pk]),
                reverse("siwak:mentor_attendance"),
                reverse("siwak:mentor_assessments"),
                reverse("siwak:mentor_task_reviews"),
            ),
        }
        for akun, urls in halaman.items():
            self.client.force_login(akun)
            for url in urls:
                with self.subTest(akun=akun.username, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotContains(response, self.TAG)
