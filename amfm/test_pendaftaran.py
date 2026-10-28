"""Kontrak SSO, identitas tepercaya, deadline, dan privasi pendaftaran."""
import datetime
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from PIL import Image
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import resolve, reverse
from django.utils import timezone

from birdep.models import BirDep
from siwak.models import Profile
from web_fuki.urls import protected_submission_media

from .models import AmfmInfo, Pendaftaran

CAS_BACKEND = "django_cas_ng.backends.CASBackend"
ATTRIBUTES = {"nama": "Mahasiswa FUKI", "npm": "2600000001", "kd_org": "01.00.12.01"}


def gambar(format="PNG"):
    buf = BytesIO()
    Image.new("RGB", (2, 2), "white").save(buf, format=format)
    return SimpleUploadedFile("follow.png", buf.getvalue(), content_type="image/png")


def masuk(client, user, attributes=None):
    client.force_login(user, backend=CAS_BACKEND)
    session = client.session
    session["attributes"] = ATTRIBUTES if attributes is None else attributes
    session.save()


class PendaftaranTests(TestCase):
    def setUp(self):
        self.url = reverse("amfm:daftar")
        self.user = get_user_model().objects.create_user(username="mahasiswa")
        self.profile = Profile.objects.create(
            user=self.user, npm=ATTRIBUTES["npm"], nama_lengkap=ATTRIBUTES["nama"], jurusan="IK",
        )
        self.info = AmfmInfo.get_solo()
        self.info.status_pendaftaran = "dibuka"
        self.info.save()
        self.itf = BirDep.objects.create(nama="ITF", logo_filename="")
        self.medkre = BirDep.objects.create(nama="Medkre", logo_filename="")
        masuk(self.client, self.user)

    def data(self, **overrides):
        return {"jenis_kelamin": "L", "kontak": "line-mahasiswa", "pilihan_1": self.itf.pk,
                "pilihan_2": self.medkre.pk, "motivasi": "Belajar dan berkontribusi bersama FUKI.",
                "bukti_follow": gambar(), **overrides}

    def daftar(self, **overrides):
        return self.client.post(self.url, self.data(**overrides))

    def test_informasi_publik_dan_registrasi_selalu_meminta_sso(self):
        self.client.logout()
        for state in ("belum_dibuka", "dibuka", "ditutup"):
            self.info.status_pendaftaran = state
            self.info.save()
            self.assertEqual(self.client.get(reverse("amfm:beranda")).status_code, 200)
            for method in (self.client.get, self.client.post):
                response = method(self.url)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(urlparse(response.url).path, reverse("siwak:cas_ng_login"))
                self.assertEqual(parse_qs(urlparse(response.url).query)["next"], [self.url])
        self.assertFalse(Pendaftaran.objects.exists())

    def test_callback_cas_mengisi_profil_dan_kembali_ke_amfm(self):
        self.client.logout()
        self.profile.delete()
        with patch("django_cas_ng.backends.get_cas_client") as client:
            client.return_value.verify_ticket.return_value = (self.user.username, ATTRIBUTES, None)
            response = self.client.get(reverse("siwak:cas_ng_login"), {"ticket": "ST-test", "next": self.url})
        self.assertRedirects(response, self.url)
        self.assertEqual(self.client.session["_auth_user_backend"], CAS_BACKEND)
        self.assertEqual(self.client.session["attributes"], ATTRIBUTES)
        self.assertEqual(Profile.objects.get(user=self.user).jurusan, "IK")

    def test_sesi_lokal_tidak_lolos_dan_tidak_berputar_ke_cas(self):
        self.client.force_login(self.user, backend="django.contrib.auth.backends.ModelBackend")
        self.assertContains(self.client.get(self.url), "Masuk dengan SSO UI", status_code=403)
        self.assertEqual(self.daftar().status_code, 403)
        response = self.client.post(reverse("amfm:masuk_sso"))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("amfm:masuk_sso")).status_code, 405)

    def test_pengguna_tanpa_role_langsung_mendapat_tiga_identitas_disabled(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.profile.role)
        for field, expected in (("nama_lengkap", ATTRIBUTES["nama"]), ("npm", ATTRIBUTES["npm"]), ("jurusan", "Ilmu Komputer")):
            self.assertTrue(response.context["form"].fields[field].disabled)
            self.assertEqual(response.context["form"][field].value(), expected)
        self.assertContains(response, "Ilmu Komputer")
        self.assertEqual([value for value, _ in response.context["form"].fields["jenis_kelamin"].choices], ["L", "P"])
        self.assertContains(response, 'data-step="3"')
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, "noindex, nofollow")

    def test_nama_lengkap_panjang_tampil_utuh_dan_tetap_dari_sso(self):
        nama = "Muhammad Lanang Zalkifla Harits"
        self.profile.nama_lengkap = nama
        self.profile.save()
        masuk(self.client, self.user, {**ATTRIBUTES, "nama": nama})
        response = self.client.get(self.url)
        self.assertContains(response, f'<p class="amfm-identity-value">{nama}</p>', html=True)
        self.assertTrue(response.context["form"].fields["nama_lengkap"].disabled)
        self.assertEqual(response.context["form"]["nama_lengkap"].value(), nama)

    def test_manipulasi_identitas_diabaikan_saat_buat_dan_revisi(self):
        self.assertEqual(self.daftar(npm="9999999999", nama_lengkap="Orang lain", jurusan="SI", user=999).status_code, 302)
        obj = Pendaftaran.objects.get()
        pk = obj.pk
        self.assertEqual((obj.user_id, obj.npm, obj.nama_lengkap, obj.jurusan),
                         (self.user.pk, ATTRIBUTES["npm"], ATTRIBUTES["nama"], "IK"))
        filename = obj.bukti_follow.name
        self.assertNotIn(obj.npm, filename)
        with patch.object(default_storage, "save") as save:
            self.assertEqual(self.daftar(bukti_follow="", kontak="line-baru", npm="9999999999").status_code, 302)
            save.assert_not_called()
        self.assertEqual(Pendaftaran.objects.count(), 1)
        obj.refresh_from_db()
        self.assertEqual((obj.pk, obj.npm, obj.kontak, obj.bukti_follow.name), (pk, ATTRIBUTES["npm"], "line-baru", filename))
        self.info.status_pendaftaran = "ditutup"
        self.info.save()
        self.assertContains(self.client.get(self.url), "Pendaftaran terkirim")

    def test_form_lama_terisi_dan_sukses_memiliki_tautan_ubah(self):
        response = self.daftar()
        self.assertEqual(response.url, self.url + "?terkirim=1")
        self.assertContains(self.client.get(response.url), "Ubah Pendaftaran")
        form_response = self.client.get(self.url)
        self.assertContains(form_response, "Kirim Ulang")
        self.assertEqual(form_response.context["form"]["kontak"].value(), "line-mahasiswa")
        self.assertEqual(form_response.context["form"]["pilihan_1"].value(), self.itf.pk)
        self.assertContains(form_response, reverse("amfm:bukti_peserta", args=[1]))

    def test_revisi_bukti_dapat_diganti_dan_dihapus(self):
        self.daftar(bukti_follow_2=gambar("JPEG"))
        obj = Pendaftaran.objects.get()
        old_names = (obj.bukti_follow.name, obj.bukti_follow_2.name)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.daftar(bukti_follow=gambar(), bukti_follow_2="", hapus_bukti_follow_2="1")
        self.assertEqual(response.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(Pendaftaran.objects.count(), 1)
        self.assertNotEqual(obj.bukti_follow.name, old_names[0])
        self.assertFalse(obj.bukti_follow_2)
        self.assertTrue(default_storage.exists(obj.bukti_follow.name))
        self.assertTrue(all(not default_storage.exists(name) for name in old_names))

    def test_revisi_boleh_menghapus_slot_pertama_jika_slot_kedua_ada(self):
        self.daftar(bukti_follow_2=gambar())
        obj = Pendaftaran.objects.get()
        old_names = (obj.bukti_follow.name, obj.bukti_follow_2.name)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.daftar(bukti_follow="", hapus_bukti_follow="1")
        self.assertEqual(response.status_code, 302)
        obj.refresh_from_db()
        self.assertFalse(obj.bukti_follow)
        self.assertEqual(obj.bukti_follow_2.name, old_names[1])
        self.assertFalse(default_storage.exists(old_names[0]))
        self.assertTrue(default_storage.exists(old_names[1]))

    def test_revisi_tidak_boleh_menghapus_bukti_terakhir(self):
        self.daftar()
        obj = Pendaftaran.objects.get()
        old_name = obj.bukti_follow.name
        response = self.daftar(bukti_follow="", hapus_bukti_follow="1")
        self.assertIn("bukti_follow", response.context["form"].errors)
        obj.refresh_from_db()
        self.assertEqual(obj.bukti_follow.name, old_name)
        self.assertTrue(default_storage.exists(old_name))

    def test_perubahan_pilihan_membatalkan_penempatan_yang_tidak_berlaku(self):
        self.daftar()
        obj = Pendaftaran.objects.get()
        obj.status, obj.penempatan = "diterima", self.itf
        obj.save(update_fields=["status", "penempatan"])
        self.assertEqual(self.daftar(bukti_follow="", pilihan_1=self.medkre.pk, pilihan_2=self.medkre.pk).status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.status, "menunggu")
        self.assertIsNone(obj.penempatan)

    def test_revisi_setelah_deadline_atau_penutupan_manual_ditolak(self):
        self.daftar()
        obj = Pendaftaran.objects.get()
        for state, deadline in (("dibuka", timezone.now() - datetime.timedelta(seconds=1)),
                                ("ditutup", timezone.now() + datetime.timedelta(days=1))):
            self.info.status_pendaftaran, self.info.ditutup_pada = state, deadline
            self.info.save()
            self.assertContains(self.client.get(self.url), "Pendaftaran terkirim")
            response = self.client.post(self.url, self.data(bukti_follow="", kontak="tidak-tersimpan"), HTTP_ACCEPT="application/json")
            self.assertEqual(response.status_code, 409)
            self.assertIn("tidak disimpan", response.json()["message"])
            obj.refresh_from_db()
            self.assertEqual(obj.kontak, "line-mahasiswa")
        self.assertEqual(Pendaftaran.objects.count(), 1)

    def test_deadline_saat_upload_revisi_mempertahankan_data_dan_bukti_lama(self):
        self.daftar()
        obj = Pendaftaran.objects.get()
        old_name = obj.bukti_follow.name
        now = timezone.now()
        self.info.ditutup_pada = now + datetime.timedelta(seconds=1)
        self.info.save()
        clock = [now]
        original_save = default_storage.save
        names = []

        def upload(*args, **kwargs):
            name = original_save(*args, **kwargs)
            names.append(name)
            clock[0] = now + datetime.timedelta(seconds=2)
            return name

        with patch("amfm.models.timezone.now", side_effect=lambda: clock[0]), patch.object(default_storage, "save", side_effect=upload):
            response = self.daftar(kontak="tidak-tersimpan", bukti_follow=gambar())
        self.assertEqual(response.status_code, 409)
        obj.refresh_from_db()
        self.assertEqual((obj.kontak, obj.bukti_follow.name), ("line-mahasiswa", old_name))
        self.assertTrue(default_storage.exists(old_name))
        self.assertEqual(len(names), 1)
        self.assertFalse(default_storage.exists(names[0]))

    def test_upload_kedua_gagal_saat_revisi_tidak_menghapus_bukti_lama(self):
        self.daftar(bukti_follow_2=gambar())
        obj = Pendaftaran.objects.get()
        old_names = (obj.bukti_follow.name, obj.bukti_follow_2.name)
        original_save = default_storage.save
        names = []

        def upload(*args, **kwargs):
            if names:
                raise OSError("storage unavailable")
            name = original_save(*args, **kwargs)
            names.append(name)
            return name

        with patch.object(default_storage, "save", side_effect=upload), self.assertRaises(OSError):
            self.daftar(bukti_follow=gambar(), bukti_follow_2=gambar(), kontak="tidak-tersimpan")
        obj.refresh_from_db()
        self.assertEqual((obj.kontak, obj.bukti_follow.name, obj.bukti_follow_2.name), ("line-mahasiswa", *old_names))
        self.assertTrue(all(default_storage.exists(name) for name in old_names))
        self.assertEqual(len(names), 1)
        self.assertFalse(default_storage.exists(names[0]))

    def test_bukti_lama_hanya_dapat_dibuka_pemilik_sso(self):
        url = reverse("amfm:bukti_peserta", args=[2])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.daftar(bukti_follow_2=gambar())
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("image/", response["Content-Type"])
        self.assertIn("no-store", response["Cache-Control"])
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        other = get_user_model().objects.create_user(username="orang-lain")
        masuk(self.client, other)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_identitas_hilang_atau_berbeda_diblokir(self):
        for attributes in ({}, {**ATTRIBUTES, "npm": "2600000002"}, {**ATTRIBUTES, "kd_org": "99.00"}, {**ATTRIBUTES, "nama": [None]}):
            masuk(self.client, self.user, attributes)
            self.assertContains(self.client.get(self.url), "Identitas SSO belum lengkap", status_code=403)
            self.assertEqual(self.daftar().status_code, 403)
        masuk(self.client, self.user)
        self.profile.delete()
        self.assertEqual(self.daftar().status_code, 403)
        self.assertFalse(Pendaftaran.objects.exists())

    def test_profil_lokal_tetap_ditolak_meski_backend_cas(self):
        self.profile.auth_source = Profile.SOURCE_LOKAL
        self.profile.save()
        self.assertEqual(self.daftar().status_code, 403)

    def test_sesi_kedaluwarsa_kembali_ke_sso_tanpa_menyimpan(self):
        session = self.client.session
        session.set_expiry(-1)
        session.save()
        self.assertEqual(self.daftar().status_code, 302)
        self.assertFalse(Pendaftaran.objects.exists())

    def test_csrf_diwajibkan_untuk_kirim_dan_ganti_sesi(self):
        client = Client(enforce_csrf_checks=True)
        masuk(client, self.user)
        self.assertEqual(client.post(self.url, self.data()).status_code, 403)
        self.assertEqual(client.post(reverse("amfm:masuk_sso")).status_code, 403)
        self.assertFalse(Pendaftaran.objects.exists())

    def test_status_jadwal_dan_penutupan_manual_ditegakkan_pada_post(self):
        now = timezone.now()
        cases = [("dibuka", now + datetime.timedelta(hours=1), None, "belum dibuka"),
                 ("dibuka", None, now, "sudah ditutup"),
                 ("ditutup", None, None, "sudah ditutup")]
        for state, start, end, text in cases:
            self.info.status_pendaftaran, self.info.dibuka_pada, self.info.ditutup_pada = state, start, end
            self.info.save()
            self.assertContains(self.daftar(), text, status_code=409)
        self.assertFalse(Pendaftaran.objects.exists())

    def test_deadline_diperiksa_lagi_setelah_upload_dan_file_dibersihkan(self):
        now = timezone.now()
        self.info.ditutup_pada = now + datetime.timedelta(seconds=1)
        self.info.save()
        clock = [now]
        original_save = default_storage.save
        names = []

        def upload(*args, **kwargs):
            name = original_save(*args, **kwargs)
            names.append(name)
            clock[0] = now + datetime.timedelta(seconds=2)
            return name

        with patch("amfm.models.timezone.now", side_effect=lambda: clock[0]), patch.object(default_storage, "save", side_effect=upload):
            response = self.daftar()
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Pendaftaran.objects.exists())
        self.assertEqual(len(names), 1)
        self.assertFalse(default_storage.exists(names[0]))

    def test_pilihan_birdept_yang_sama_diterima(self):
        response = self.daftar(pilihan_2=self.itf.pk)
        self.assertEqual(response.status_code, 302)
        obj = Pendaftaran.objects.get()
        self.assertEqual((obj.pilihan_1_id, obj.pilihan_2_id), (self.itf.pk, self.itf.pk))

    def test_birdept_tidak_aktif_ditolak(self):
        self.medkre.is_active = False
        self.medkre.save()
        self.assertIn("pilihan_2", self.daftar().context["form"].errors)
        self.assertFalse(Pendaftaran.objects.exists())

    def test_validasi_upload_isi_format_ukuran_dan_isian_wajib(self):
        files = [SimpleUploadedFile("fake.png", b"not an image", content_type="image/png"), gambar("GIF")]
        large = gambar()
        large.size = 2 * 1024 * 1024 + 1
        # Test ukuran pada form, karena test client menghitung ulang ukuran stream.
        from .forms import PendaftaranForm
        form = PendaftaranForm(self.data(), {"bukti_follow": large}, profile=self.profile)
        self.assertFalse(form.is_valid())
        self.assertIn("bukti_follow", form.errors)
        for file in files:
            self.assertIn("bukti_follow", self.daftar(bukti_follow=file).context["form"].errors)
        for field in ("jenis_kelamin", "kontak", "motivasi"):
            self.assertIn(field, self.daftar(**{field: ""}).context["form"].errors)
        self.assertFalse(Pendaftaran.objects.exists())

    def test_portofolio_opsional_untuk_itf_medkre(self):
        self.assertEqual(self.daftar(portofolio="https://example.com/portfolio").status_code, 302)
        self.assertEqual(Pendaftaran.objects.get().portofolio, "https://example.com/portfolio")

    def test_npm_tetap_unik_di_database(self):
        self.daftar()
        obj = Pendaftaran.objects.get()
        obj.pk = None
        obj.user = get_user_model().objects.create_user(username="lain")
        with self.assertRaises(IntegrityError), transaction.atomic():
            obj.save()

    def test_npm_milik_akun_lain_tidak_membocorkan_jawaban(self):
        self.daftar()
        obj = Pendaftaran.objects.get()
        obj.user = get_user_model().objects.create_user(username="pemilik-lama")
        obj.save()
        response = self.client.get(self.url)
        self.assertContains(response, "NPM sudah terdaftar", status_code=409)
        self.assertNotContains(response, obj.kontak, status_code=409)

    def test_bukti_hanya_bisa_diunduh_admin_dengan_izin_model(self):
        self.daftar()
        obj = Pendaftaran.objects.get()
        url = reverse("admin:amfm_pendaftaran_bukti", args=[obj.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        staff = get_user_model().objects.create_user(username="pengelola", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url).status_code, 403)
        staff.user_permissions.add(Permission.objects.get(codename="view_pendaftaran"))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))
        self.assertEqual(resolve("/media/" + obj.bukti_follow.name).func, protected_submission_media)
        self.assertEqual(self.client.get("/media/" + obj.bukti_follow.name).status_code, 404)

    def test_bukti_dihapus_setelah_penghapusan_data_commit(self):
        self.daftar()
        obj = Pendaftaran.objects.get()
        name = obj.bukti_follow.name
        with self.captureOnCommitCallbacks(execute=True):
            obj.delete()
        self.assertFalse(default_storage.exists(name))

    def test_dua_bukti_tersimpan_dan_keduanya_dihapus_setelah_commit(self):
        response = self.daftar(bukti_follow_2=gambar("JPEG"))
        self.assertEqual(response.status_code, 302)
        obj = Pendaftaran.objects.get()
        names = [obj.bukti_follow.name, obj.bukti_follow_2.name]
        self.assertNotEqual(*names)
        self.assertTrue(all(default_storage.exists(name) for name in names))
        with self.captureOnCommitCallbacks(execute=True):
            obj.delete()
        self.assertTrue(all(not default_storage.exists(name) for name in names))

    def test_boleh_hanya_menggunakan_slot_kedua(self):
        response = self.client.post(self.url, self.data(bukti_follow="", bukti_follow_2=gambar()))
        self.assertEqual(response.status_code, 302)
        obj = Pendaftaran.objects.get()
        self.assertFalse(obj.bukti_follow)
        self.assertTrue(obj.bukti_follow_2)

    def test_json_validasi_tidak_mengunggah_file_dan_bisa_dikirim_ulang(self):
        with patch.object(default_storage, "save", wraps=default_storage.save) as save:
            response = self.client.post(self.url, self.data(pilihan_2=999999, bukti_follow_2=gambar()), HTTP_ACCEPT="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("pilihan_2", response.json()["errors"])
            self.assertEqual(response.json()["step"], 2)
            save.assert_not_called()
            self.assertFalse(Pendaftaran.objects.exists())
        response = self.client.post(self.url, self.data(bukti_follow_2=gambar()), HTTP_ACCEPT="application/json")
        self.assertEqual(response.json(), {"redirect": self.url + "?terkirim=1"})
        self.assertEqual(Pendaftaran.objects.count(), 1)
        self.assertTrue(Pendaftaran.objects.get().bukti_follow_2)

    def test_json_memvalidasi_minimal_satu_bukti_dan_format_slot_kedua(self):
        response = self.client.post(self.url, self.data(bukti_follow=""), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("bukti_follow", response.json()["errors"])
        response = self.client.post(self.url, self.data(bukti_follow_2=gambar("GIF")), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("bukti_follow_2", response.json()["errors"])
        self.assertFalse(Pendaftaran.objects.exists())

    def test_slot_kedua_juga_maksimal_dua_mb(self):
        from .forms import PendaftaranForm
        file = gambar()
        file.size = 2 * 1024 * 1024 + 1
        form = PendaftaranForm(self.data(), {"bukti_follow": gambar(), "bukti_follow_2": file}, profile=self.profile)
        self.assertFalse(form.is_valid())
        self.assertIn("bukti_follow_2", form.errors)

    def test_json_sesi_hilang_meminta_sso_dan_csrf_tetap_diwajibkan(self):
        self.client.logout()
        response = self.client.post(self.url, {}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 401)
        destination = response.json()["redirect"]
        self.assertEqual(urlparse(destination).path, reverse("siwak:cas_ng_login"))
        self.assertEqual(parse_qs(urlparse(destination).query)["next"], [self.url])
        client = Client(enforce_csrf_checks=True)
        masuk(client, self.user)
        self.assertEqual(client.post(self.url, self.data(), HTTP_ACCEPT="application/json").status_code, 403)
        self.assertFalse(Pendaftaran.objects.exists())

    def test_dua_bukti_dibersihkan_jika_deadline_lewat_saat_upload(self):
        now = timezone.now()
        self.info.ditutup_pada = now + datetime.timedelta(seconds=1)
        self.info.save()
        clock = [now]
        original_save = default_storage.save
        names = []

        def upload(*args, **kwargs):
            name = original_save(*args, **kwargs)
            names.append(name)
            clock[0] = now + datetime.timedelta(seconds=2)
            return name

        with patch("amfm.models.timezone.now", side_effect=lambda: clock[0]), patch.object(default_storage, "save", side_effect=upload):
            response = self.daftar(bukti_follow_2=gambar())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(names), 2)
        self.assertTrue(all(not default_storage.exists(name) for name in names))
        self.assertFalse(Pendaftaran.objects.exists())

    def test_bukti_pertama_dibersihkan_jika_upload_kedua_gagal(self):
        original_save = default_storage.save
        names = []

        def upload(*args, **kwargs):
            if names:
                raise OSError("storage unavailable")
            name = original_save(*args, **kwargs)
            names.append(name)
            return name

        with patch.object(default_storage, "save", side_effect=upload), self.assertRaises(OSError):
            self.daftar(bukti_follow_2=gambar())
        self.assertFalse(default_storage.exists(names[0]))
        self.assertFalse(Pendaftaran.objects.exists())

    def test_dua_bukti_di_django_admin_memerlukan_izin(self):
        self.daftar(bukti_follow_2=gambar())
        obj = Pendaftaran.objects.get()
        url = reverse("admin:amfm_pendaftaran_bukti_nomor", args=[obj.pk, 2])
        self.assertEqual(self.client.get(url).status_code, 302)
        staff = get_user_model().objects.create_user(username="pengelola-kedua", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url).status_code, 403)
        staff.user_permissions.add(Permission.objects.get(codename="view_pendaftaran"))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))
        self.assertEqual(self.client.get(reverse("admin:amfm_pendaftaran_bukti_nomor", args=[obj.pk, 3])).status_code, 404)


class PengirimanBersamaanTests(TransactionTestCase):
    def test_dua_post_bersamaan_hanya_membuat_satu_pendaftaran(self):
        user = get_user_model().objects.create_user(username="mahasiswa")
        Profile.objects.create(user=user, npm=ATTRIBUTES["npm"], nama_lengkap=ATTRIBUTES["nama"], jurusan="IK")
        info = AmfmInfo.get_solo()
        info.status_pendaftaran = "dibuka"
        info.save()
        a = BirDep.objects.create(nama="ITF", logo_filename="")
        b = BirDep.objects.create(nama="Medkre", logo_filename="")
        clients = [Client(), Client()]
        for client in clients:
            masuk(client, user)

        def send(client):
            connections.close_all()
            try:
                return client.post(reverse("amfm:daftar"), {
                    "jenis_kelamin": "P", "kontak": "line-id", "pilihan_1": a.pk,
                    "pilihan_2": b.pk, "motivasi": "Ingin belajar", "bukti_follow": gambar(),
                }).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertTrue(all(status in (200, 302) for status in pool.map(send, clients)))
        self.assertEqual(Pendaftaran.objects.count(), 1)
