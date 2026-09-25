"""Pengawasan pengurus atas data mentoring, catatan privat mentee, dan
penyaring kelompok/sesi di panel SIWAK.

Regression guard yang paling penting di sini: `Profile.notes` hanya boleh
terbaca dan tersunting oleh pengurus dan mentor kelompok mentee itu — tidak
pernah oleh mentee sendiri, mentee lain, mentor kelompok lain, atau pengunjung.
"""

import datetime
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from main.context_processors import monitoring

from .mentor_forms import FIELD_CLASSES, CatatanMenteeForm
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
from .services.mentor import boleh_baca_catatan, boleh_ubah_catatan
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

    def test_staff_can_read_it_but_never_write_it(self):
        """Catatan milik mentor kelompoknya: pengurus hanya membaca, dan
        POST langsung ke pintunya pun ditolak — bukan sekadar form disembunyikan."""
        self.client.force_login(self.staf)
        halaman = reverse("siwak:panel_mentee_detail", args=[self.mentee_a.pk])

        response = self.client.get(halaman)
        self.assertContains(response, CATATAN)
        self.assertContains(response, "Hanya baca")
        self.assertNotContains(response, self.url_simpan)
        self.assertNotContains(response, 'name="notes"')
        self.assertContains(
            self.client.get(reverse("siwak:panel_kelompok_detail", args=[self.kelompok_a.pk])), CATATAN
        )

        self.assertEqual(self._simpan().status_code, 403)
        self.assertEqual(self._catatan(), CATATAN)
        self.assertTrue(boleh_baca_catatan(self.staf, self.mentee_a))
        self.assertFalse(boleh_ubah_catatan(self.staf, self.mentee_a))

    def test_a_staff_account_that_is_also_the_groups_mentor_may_write_it(self):
        """Yang menentukan hak menyunting adalah memegang kelompoknya, bukan is_staff."""
        self.mentor_a.user.is_staff = True
        self.mentor_a.user.save(update_fields=["is_staff"])
        self.client.force_login(self.mentor_a.user)

        self._simpan()

        self.assertEqual(self._catatan(), "Catatan baru")

    def test_the_panel_says_so_when_the_mentor_has_not_written_one(self):
        self.mentee_a.notes = "   "
        self.mentee_a.save(update_fields=["notes"])
        self.client.force_login(self.staf)

        response = self.client.get(reverse("siwak:panel_mentee_detail", args=[self.mentee_a.pk]))

        self.assertContains(response, "Belum ada catatan dari mentor.")

    def test_the_django_admin_shows_it_read_only(self):
        admin = User.objects.create_superuser(username="super", password="x")
        self.client.force_login(admin)

        response = self.client.get(reverse("admin:siwak_profile_change", args=[self.mentee_a.pk]))

        self.assertContains(response, CATATAN)
        self.assertNotContains(response, 'name="notes"')

    def test_the_mentor_field_is_styled_like_session_feedback_and_has_a_placeholder(self):
        """Regresi: `widgets` sempat terlepas dari Meta sehingga isiannya polos."""
        self.kelompok_a.mentoring_sessions.filter(nomor=1).update(is_active=True)
        self.client.force_login(self.mentor_a.user)
        halaman = reverse("siwak:mentor_mentee_detail", args=[self.mentee_a.pk])

        html = self.client.get(halaman).content.decode()
        catatan = re.search(r'<textarea[^>]*name="notes"[^>]*>', html).group(0)
        feedback = re.search(r'<textarea[^>]*name="[^"]*feedback"[^>]*>', html).group(0)
        self.assertIn(f'class="{FIELD_CLASSES}"', catatan)
        self.assertIn(f'class="{FIELD_CLASSES}"', feedback)
        self.assertIn('placeholder="Belum ada catatan.', catatan)

    def test_clearing_it_keeps_the_placeholder_and_says_it_was_removed(self):
        self.client.force_login(self.mentor_a.user)
        halaman = reverse("siwak:mentor_mentee_detail", args=[self.mentee_a.pk])

        response = self._simpan(isi="", next=halaman)

        self.assertEqual(self._catatan(), "")
        response = self.client.get(halaman)
        self.assertContains(response, "Catatan untuk Mentee A dihapus.")
        self.assertContains(response, 'placeholder="Belum ada catatan.')

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

        self.assertFalse(boleh_ubah_catatan(tanpa_kelompok.user, mentee_lepas))
        self.assertFalse(boleh_baca_catatan(tanpa_kelompok.user, mentee_lepas))
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

    def test_no_page_shows_it_to_anyone_outside_staff_and_the_groups_mentor(self):
        """Sapu semua halaman yang bisa dibuka mentee, mentor, dan pengunjung."""
        tugas = Tugas.objects.create(
            judul_tugas="Refleksi", deskripsi="d", deadline=timezone.now() + datetime.timedelta(days=1)
        )
        pemindai = User.objects.create_user(username="panitia-gate")
        pemindai.user_permissions.add(Permission.objects.get(codename="pindai_registrasi"))
        halaman = [
            reverse("siwak:landing"),
            reverse("siwak:tugas_list"),
            reverse("siwak:tugas_detail", args=[tugas.pk]),
            reverse("siwak:mentee_feedback_history"),
            reverse("siwak:mentor_dashboard"),
            reverse("siwak:mentor_mentee_detail", args=[self.mentee_a.pk]),
            reverse("siwak:mentor_attendance"),
            reverse("siwak:mentor_assessments"),
            reverse("siwak:mentor_task_reviews"),
            reverse("siwak:panel_mentee_detail", args=[self.mentee_a.pk]),
            reverse("siwak:panel_kelompok_detail", args=[self.kelompok_a.pk]),
            reverse("siwak:pindai_beranda"),
        ]
        for user in (None, self.mentee_a.user, self.teman_a.user, self.mentor_b.user, pemindai):
            self.client.logout()
            if user:
                self.client.force_login(user)
            for url in halaman:
                with self.subTest(user=user and user.username, url=url):
                    self.assertNotIn(CATATAN, self.client.get(url).content.decode())

    def test_it_is_escaped_wherever_it_is_shown(self):
        self.mentee_a.notes = "<script>alert(1)</script>"
        self.mentee_a.save(update_fields=["notes"])

        self.client.force_login(self.staf)
        for url in (
            reverse("siwak:panel_mentee_detail", args=[self.mentee_a.pk]),
            reverse("siwak:panel_kelompok_detail", args=[self.kelompok_a.pk]),
        ):
            self.assertNotContains(self.client.get(url), "<script>alert(1)</script>")
        self.client.force_login(self.mentor_a.user)
        self.assertNotContains(
            self.client.get(reverse("siwak:mentor_mentee_detail", args=[self.mentee_a.pk])),
            "<script>alert(1)</script>",
        )

    def test_the_old_mentor_loses_access_once_the_mentee_moves_group(self):
        self.mentee_a.kelompok = self.kelompok_b
        self.mentee_a.save(update_fields=["kelompok"])
        self.client.force_login(self.mentor_a.user)

        self.assertEqual(self._simpan().status_code, 403)
        self.assertEqual(self._catatan(), CATATAN)

    def test_saving_it_never_undoes_a_group_change_made_meanwhile(self):
        """Mentor membuka halaman, pengurus memindah kelompok, lalu mentor menyimpan
        catatan: yang ditulis hanya `notes`, bukan seluruh baris yang sudah basi."""
        basi = Profile.objects.get(pk=self.mentee_a.pk)
        Profile.objects.filter(pk=self.mentee_a.pk).update(kelompok=self.kelompok_b)

        form = CatatanMenteeForm({"notes": "Catatan baru"}, instance=basi)
        self.assertTrue(form.is_valid())
        form.save()

        self.mentee_a.refresh_from_db()
        self.assertEqual(self.mentee_a.notes, "Catatan baru")
        self.assertEqual(self.mentee_a.kelompok_id, self.kelompok_b.pk)


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

    def test_the_mentee_page_shows_feedback_from_every_mentor_even_without_attendance(self):
        """Kelompok boleh dipegang dua mentor; feedback tanpa presensi tetap data mentor."""
        kedua = _profil("2100000071", "Kak Budi", Profile.ROLE_MENTOR, self.kelompok)
        sesi2 = self.kelompok.mentoring_sessions.get(nomor=2)
        MentorFeedback.objects.create(session=sesi2, peserta=self.mentee, mentor=self.mentor, isi="Dari Ahmad.")
        MentorFeedback.objects.create(session=sesi2, peserta=self.mentee, mentor=kedua, isi="Dari Budi.")
        self.client.force_login(self.staf)

        response = self.client.get(self.url)

        self.assertContains(response, "Dari Ahmad.")
        self.assertContains(response, "Dari Budi.")

    def test_the_mentee_page_works_before_login_and_placement(self):
        belum = Profile.objects.create(nama_lengkap="Belum Login", npm="2500000079", role=Profile.ROLE_MENTEE)
        self.client.force_login(self.staf)

        response = self.client.get(reverse("siwak:panel_mentee_detail", args=[belum.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Belum ditempatkan di kelompok.")

    def test_the_task_answers_page_shows_the_mentors_grade_and_feedback(self):
        self.client.force_login(self.staf)

        response = self.client.get(reverse("siwak:panel_jawaban", args=[self.tugas.pk]))

        self.assertContains(response, "Nilai 92")
        self.assertContains(response, "Refleksi yang jujur.")
        self.assertContains(response, "Kelompok 7")
        self.assertContains(response, f'href="{self.url}"')
        self.assertEqual(response.context["jumlah_dinilai"], 1)

    def test_the_task_answers_export_carries_the_group_grade_and_feedback(self):
        self.client.force_login(self.staf)

        response = self.client.get(reverse("siwak:panel_jawaban_csv", args=[self.tugas.pk]))

        kepala, baris = response.content.decode().splitlines()
        self.assertTrue(kepala.startswith("Nama,NPM,Kelompok,Status,Waktu Kumpul,"))
        self.assertTrue(kepala.endswith("Nilai Mentor,Feedback Mentor,Dinilai Oleh"))
        self.assertIn("Kelompok 7", baris)
        self.assertTrue(baris.endswith("92,Refleksi yang jujur.,Kak Ahmad"))

    def test_the_group_page_counts_active_sessions_out_of_all_of_them_when_narrowed(self):
        """Menyaring kisi ke satu sesi tidak boleh mengubah "Sesi aktif 2 / 4" jadi "2 / 1"."""
        self.kelompok.mentoring_sessions.filter(nomor__in=[1, 2]).update(is_active=True)
        self.client.force_login(self.staf)

        response = self.client.get(
            reverse("siwak:panel_kelompok_detail", args=[self.kelompok.pk]), {"sesi": "3"}
        )

        html = response.content.decode()
        kartu = re.search(r"(\d+)<span[^>]*> / (\d+)</span></p>\s*<p[^>]*>Sesi aktif", html)
        self.assertEqual(kartu.groups(), ("2", "4"))

    def test_attendance_statuses_get_distinct_colours_on_every_panel_page(self):
        """Hadir hijau, Izin kuning, Tidak Hadir merah — di mana pun enum ini tampil."""
        sesi2 = self.kelompok.mentoring_sessions.get(nomor=2)
        sesi3 = self.kelompok.mentoring_sessions.get(nomor=3)
        MentoringAttendance.objects.create(session=sesi2, peserta=self.mentee, status="izin")
        MentoringAttendance.objects.create(session=sesi3, peserta=self.mentee, status="tidak_hadir")
        acara = SiwakEvent.objects.create(judul="Main Event")
        EventRSVP.objects.create(event=acara, user=self.mentee.user, kehadiran="hadir")
        EventRSVP.objects.create(event=acara, user=self.teman.user, kehadiran="izin",
                                 alasan_izin="Sakit")
        warna = {
            "Hadir": "bg-green-100", "Izin": "bg-amber-100", "Tidak Hadir": "bg-red-100",
        }
        self.client.force_login(self.staf)

        for url, label in (
            (self.url, ("Hadir", "Izin", "Tidak Hadir")),
            (reverse("siwak:panel_kelompok_detail", args=[self.kelompok.pk]), ("Hadir", "Izin", "Tidak Hadir")),
            (reverse("siwak:panel_daftar", args=["presensi"]), ("Hadir", "Izin", "Tidak Hadir")),
            (reverse("siwak:panel_rsvp", args=[acara.pk]), ("Hadir", "Izin")),
        ):
            html = self.client.get(url).content.decode()
            for teks in label:
                with self.subTest(url=url, status=teks):
                    self.assertRegex(html, rf'class="[^"]*{warna[teks]}[^"]*">{teks}</span>')

    def test_the_mentor_review_on_the_answers_page_stands_out_on_navy(self):
        self.client.force_login(self.staf)

        html = self.client.get(reverse("siwak:panel_jawaban", args=[self.tugas.pk])).content.decode()

        self.assertRegex(html, r'<div class="rounded-xl bg-navy[^"]*">\s*<p[^>]*>Penilaian mentor</p>')


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

    def test_the_mentor_lists_filter_by_group(self):
        mentor_a = _profil("2100000001", "Mentor A", Profile.ROLE_MENTOR, self.kelompok_a)
        _profil("2100000002", "Mentor B", Profile.ROLE_MENTOR, self.kelompok_b)
        lokal_a = Profile.objects.create(
            user=User.objects.create_user(username="mentor-lokal-a"), nama_lengkap="Lokal A",
            role=Profile.ROLE_MENTOR, auth_source=Profile.SOURCE_LOKAL, kelompok=self.kelompok_a,
        )
        Profile.objects.create(
            user=User.objects.create_user(username="mentor-lokal-b"), nama_lengkap="Lokal B",
            role=Profile.ROLE_MENTOR, auth_source=Profile.SOURCE_LOKAL, kelompok=self.kelompok_b,
        )
        a = str(self.kelompok_a.pk)

        _, baris = self._daftar("mentor", kelompok=a)
        self.assertEqual(baris, [mentor_a])
        _, baris = self._daftar("mentor_lokal", kelompok=a)
        self.assertEqual(baris, [lokal_a])

    def test_the_rsvp_page_filters_by_group_alongside_role_and_search(self):
        acara = SiwakEvent.objects.create(judul="Main Event")
        for profil in (self.ani, self.budi):
            EventRSVP.objects.create(event=acara, user=profil.user, status_kehadiran="hadir")
        a = str(self.kelompok_a.pk)
        url = reverse("siwak:panel_rsvp", args=[acara.pk])

        response = self.client.get(url, {"kelompok": a, "role": "mentee"})

        self.assertEqual([r.user_id for r in response.context["halaman"].object_list], [self.ani.user_id])
        # Ringkasan dan tab tetap menghitung seluruh acara, bukan hasil saringan.
        self.assertEqual(dict(response.context["ringkasan_rsvp"])["Total RSVP"], 2)
        self.assertTrue(all(f"kelompok={a}" in t["url"] for t in response.context["tab_peran"]))
        self.assertIn(f"kelompok={a}", response.context["kueri"])
        self.assertContains(response, f'<option value="{a}" selected>Kelompok A</option>', html=True)

        # Nilai asal-asalan diabaikan, bukan dikirim ke query.
        response = self.client.get(url, {"kelompok": "abc"})
        self.assertEqual(response.context["halaman"].paginator.count, 2)

    def test_the_rsvp_export_follows_the_group_and_names_it(self):
        acara = SiwakEvent.objects.create(judul="Main Event")
        for profil in (self.ani, self.budi):
            EventRSVP.objects.create(event=acara, user=profil.user)

        response = self.client.get(
            reverse("siwak:panel_rsvp_csv", args=[acara.pk]), {"kelompok": self.kelompok_b.pk}
        )

        kepala, *baris = response.content.decode().splitlines()
        self.assertIn("Kelompok", kepala.split(","))
        self.assertEqual(len(baris), 1)
        self.assertIn("Budi", baris[0])
        self.assertIn("Kelompok B", baris[0])

    def test_the_task_answers_page_and_export_filter_by_group(self):
        tugas = Tugas.objects.create(
            judul_tugas="Refleksi", deskripsi="d", deadline=timezone.now() + datetime.timedelta(days=1)
        )
        for profil in (self.ani, self.budi):
            TugasSubmission.objects.create(tugas=tugas, user=profil.user)
        a = str(self.kelompok_a.pk)

        response = self.client.get(reverse("siwak:panel_jawaban", args=[tugas.pk]), {"kelompok": a})

        self.assertEqual([b["nama"] for b in response.context["baris"]], ["Ani"])
        self.assertIn(f"kelompok={a}", response.context["kueri_unduh"])
        self.assertContains(response, f'<option value="{a}" selected>Kelompok A</option>', html=True)

        response = self.client.get(reverse("siwak:panel_jawaban_csv", args=[tugas.pk]), {"kelompok": a})
        _, *baris = response.content.decode().splitlines()
        self.assertEqual(len(baris), 1)
        self.assertIn("Ani", baris[0])


@override_settings(DEPLOY_ENV="production")
class ClarityTests(TestCase):
    """Microsoft Clarity records sessions, page text included: only for guests
    who are not logged in, only in production, and never on internal pages."""

    TAG = "clarity.ms/tag/"

    def _publik(self):
        return ("/", reverse("siwak:landing"), reverse("siwak:kelompok_search"), reverse("siwak:login"))

    def test_guests_on_public_pages_in_production_get_clarity(self):
        for url in self._publik():
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), self.TAG)

    def test_non_production_never_loads_clarity(self):
        for env in ("staging", "development"):
            with self.settings(DEPLOY_ENV=env):
                for url in self._publik():
                    with self.subTest(env=env, url=url):
                        self.assertNotContains(self.client.get(url), self.TAG)

    def test_logged_in_users_never_load_clarity_even_on_public_pages(self):
        mentee = _profil("2500000009", "Mentee Z", Profile.ROLE_MENTEE)
        # Tanpa halaman login: user yang sudah masuk langsung diteruskan dari sana.
        publik = [url for url in self._publik() if url != reverse("siwak:login")]
        for akun in (mentee.user, User.objects.create_user(username="pengurus", is_staff=True)):
            self.client.force_login(akun)
            for url in publik:
                with self.subTest(akun=akun.username, url=url):
                    self.assertNotContains(self.client.get(url), self.TAG)

    def test_excluded_prefixes_still_hold_for_guests(self):
        """Second safety net behind the login rule, checked on path_info so a
        site mounted under a SCRIPT_NAME cannot slip past it."""
        rf = RequestFactory()

        def aktif(path, **extra):
            request = rf.get(path, **extra)
            request.user = AnonymousUser()
            return monitoring(request)["CLARITY_AKTIF"]

        for path in ("/siwak/admin/", "/siwak/mentor/", "/siwak/qr/abc/", "/siwak/pindai/"):
            with self.subTest(path=path):
                self.assertFalse(aktif(path))
        self.assertTrue(aktif("/siwak/"))
        # request.path would be "/fuki/siwak/admin/" here and miss the prefix.
        self.assertFalse(aktif("/siwak/admin/", SCRIPT_NAME="/fuki"))

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
                # Daftar RSVP panitia: nama + NPM semua peserta acara.
                reverse("siwak:pindai_rsvp", args=[rsvp.event_id]),
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
