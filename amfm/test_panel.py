"""Kontrak seleksi, akses panel, statistik, dan pengelolaan AMFM."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase

from birdep.models import BirDep
from .models import Pendaftaran
from .panel_forms import KeputusanForm
from .services.seleksi import simpan_keputusan, ubah_status_massal


class PanelFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.itf = BirDep.objects.create(nama="ITF", logo_filename="")
        cls.medkre = BirDep.objects.create(nama="Medkre", logo_filename="")
        cls.lain = BirDep.objects.create(nama="PSDM", logo_filename="")
        cls.peserta = get_user_model().objects.create_user(username="peserta-amfm")
        cls.obj = Pendaftaran.objects.create(
            user=cls.peserta, npm="2600000001", nama_lengkap="Peserta AMFM", jurusan="IK",
            jenis_kelamin="L", id_line="id_line", pilihan_1=cls.itf, pilihan_2=cls.medkre, motivasi="Belajar",
        )



class SeleksiTests(PanelFixture):
    def test_keputusan_mewajibkan_salah_satu_pilihan_dan_membersihkan_penempatan(self):
        for penempatan in (None, self.lain.pk):
            with self.assertRaises(ValidationError):
                simpan_keputusan(self.obj.pk, "diterima", penempatan)
        obj = simpan_keputusan(self.obj.pk, "diterima", self.itf.pk)
        self.assertEqual(obj.penempatan_id, self.itf.pk)
        obj = simpan_keputusan(self.obj.pk, "ditolak", self.itf.pk)
        self.assertIsNone(obj.penempatan_id)
        with self.assertRaises(ValidationError):
            simpan_keputusan(self.obj.pk, "asing", None)

    def test_massal_tidak_menyimpan_sebagian(self):
        user = get_user_model().objects.create_user(username="kedua")
        kedua = Pendaftaran.objects.create(
            user=user, npm="2600000002", nama_lengkap="Kedua", jurusan="SI", jenis_kelamin="P",
            id_line="id_line", pilihan_1=self.itf, pilihan_2=self.medkre,
            motivasi="Belajar", penempatan=self.itf,
        )
        with self.assertRaises(ValidationError):
            ubah_status_massal([kedua.pk, self.obj.pk], "diterima")
        kedua.refresh_from_db()
        self.assertEqual(kedua.status, "menunggu")
        self.assertEqual(ubah_status_massal([kedua.pk, self.obj.pk], "ditolak"), 2)
        kedua.refresh_from_db()
        self.assertIsNone(kedua.penempatan)
        with self.assertRaises(ValidationError):
            ubah_status_massal([kedua.pk, 999999], "menunggu")

    def test_form_django_admin_dan_panel_memakai_aturan_yang_sama(self):
        self.assertFalse(KeputusanForm({"status": "diterima", "penempatan": ""}, instance=self.obj).is_valid())
        self.assertFalse(KeputusanForm({"status": "diterima", "penempatan": self.lain.pk}, instance=self.obj).is_valid())
        form = KeputusanForm({"status": "diterima", "penempatan": self.itf.pk}, instance=self.obj)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        form = KeputusanForm({"status": "menunggu", "penempatan": self.itf.pk}, instance=self.obj)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().penempatan)


class PanelTests(PanelFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = get_user_model().objects.create_user(username="admin-amfm", password="test-password-123")
        cls.admin.user_permissions.add(*Permission.objects.filter(content_type__app_label="amfm"))

    def setUp(self):
        self.client.force_login(self.admin)

    def test_navbar_menampilkan_panel_untuk_permission_dari_grup(self):
        from django.contrib.auth.models import Group
        from django.urls import reverse
        url = reverse("amfm:beranda")
        self.client.logout()
        self.assertNotContains(self.client.get(url), "Admin Panel AM-FM")
        self.client.force_login(self.peserta)
        self.assertNotContains(self.client.get(url), "Admin Panel AM-FM")
        group = Group.objects.create(name="Pengelola AM-FM")
        group.permissions.add(Permission.objects.get(content_type__app_label="amfm", codename="view_pendaftaran"))
        self.peserta.groups.add(group)
        self.assertContains(self.client.get(url), "Admin Panel AM-FM", count=2)

    def test_navigasi_utama_selalu_di_atas_tab_dan_menandai_halaman_aktif(self):
        from django.urls import reverse
        for name in ("panel_pengaturan", "panel_konten"):
            response = self.client.get(reverse("amfm:" + name))
            self.assertNotContains(response, 'aria-label="Navigasi admin AM-FM"')
            self.assertContains(response, 'aria-label="Pengelolaan AM-FM"')
            self.assertContains(response, 'amfm-nav-active')
        response = self.client.get(reverse("amfm:panel_beranda"))
        self.assertContains(response, 'aria-label="Navigasi admin AM-FM"')
        self.assertContains(response, 'aria-label="Pengelolaan AM-FM"')
        self.assertLess(response.content.index(b'aria-label="Pengelolaan AM-FM"'), response.content.index(b'aria-label="Navigasi admin AM-FM"'))
        self.assertContains(response, 'amfm-dashboard-tab', count=2)
        self.assertTrue(self.client.get(reverse("amfm:panel_konten_daftar", args=["benefit"])).context["menu_konten"][0]["aktif"])

    def test_semua_kolom_data_dapat_diurut_dengan_filter_tetap_terjaga(self):
        from urllib.parse import parse_qs, urlparse
        from django.urls import reverse
        user = get_user_model().objects.create_user(username="nama-urut")
        Pendaftaran.objects.create(user=user, npm="2600000002", nama_lengkap="Anisa", jurusan="SI",
                                    jenis_kelamin="P", id_line="id_line", pilihan_1=self.medkre,
                                    pilihan_2=self.itf, motivasi="Belajar", status="diterima", penempatan=self.itf)
        url = reverse("amfm:panel_daftar")
        response = self.client.get(url, {"urut": "nama", "q": "a", "birdept": self.itf.pk, "page": "2"})
        self.assertEqual([obj.nama_lengkap for obj in response.context["halaman"]], ["Anisa", "Peserta AMFM"])
        self.assertEqual(len(response.context["kepala_urut"]), 7)
        kepala = next(item for item in response.context["kepala_urut"] if item["label"] == "Nama")
        self.assertTrue(kepala["aktif"])
        query = parse_qs(urlparse(kepala["url"]).query)
        self.assertEqual(query, {"q": ["a"], "birdept": [str(self.itf.pk)], "urut": ["nama"], "arah": ["turun"]})
        response = self.client.get(url, {"urut": "nama", "arah": "turun"})
        self.assertEqual([obj.nama_lengkap for obj in response.context["halaman"]], ["Peserta AMFM", "Anisa"])
        self.assertContains(response, 'aria-sort="descending"')
        response = self.client.get(url, {"urut": "penempatan"})
        self.assertEqual([obj.nama_lengkap for obj in response.context["halaman"]], ["Anisa", "Peserta AMFM"])
        self.assertEqual(self.client.get(url, {"urut": "field_tidak_ada"}).status_code, 200)

    def test_status_pendaftaran_menampilkan_pilihan_tersimpan(self):
        from django.urls import reverse
        from .models import AmfmInfo
        url = reverse("amfm:panel_pengaturan")
        info = AmfmInfo.get_solo()
        for status in ("belum_dibuka", "dibuka", "ditutup"):
            info.status_pendaftaran = status
            info.save()
            response = self.client.get(url)
            self.assertEqual(response.context["form"]["status_pendaftaran"].value(), status)
            self.assertNotContains(response, "Status efektif saat ini")

    def test_panel_bukti_kedua_tetap_terotorisasi(self):
        from django.urls import reverse
        from .test_pendaftaran import gambar
        self.obj.nomor_whatsapp = "08123456789"
        self.obj.save(update_fields=["nomor_whatsapp"])
        self.obj.bukti_follow_2.save("bukti.png", gambar())
        url = reverse("amfm:panel_bukti_nomor", args=[self.obj.pk, 2])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))
        detail = self.client.get(reverse("amfm:panel_detail", args=[self.obj.pk]))
        self.assertContains(detail, url)
        self.assertContains(detail, "08123456789")
        self.assertContains(detail, self.obj.id_line)
        self.assertContains(detail, "@fukifasilkom")
        self.assertEqual(self.client.get(reverse("amfm:panel_bukti_nomor", args=[self.obj.pk, 3])).status_code, 404)
        self.client.force_login(self.peserta)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_seluruh_halaman_panel_render_dan_tidak_diindeks(self):
        from django.urls import reverse
        for name, args in [
            ("panel_beranda", []), ("panel_daftar", []), ("panel_detail", [self.obj.pk]),
            ("panel_pengaturan", []), ("panel_konten", []),
            ("panel_konten_daftar", ["benefit"]), ("panel_konten_daftar", ["timeline"]),
            ("panel_konten_tambah", ["benefit"]), ("panel_konten_tambah", ["timeline"]),
            ("panel_hapus", [self.obj.pk]),
        ]:
            with self.subTest(name=name, args=args):
                response = self.client.get(reverse("amfm:" + name, args=args))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "noindex, nofollow")
                self.assertIn("no-store", response["Cache-Control"])

    def test_login_amfm_tujuan_dan_akun_khusus_tanpa_is_staff(self):
        from django.urls import reverse
        from siwak.akses import bagian_utama
        self.client.logout()
        response = self.client.post(reverse("amfm:panel_login"), {"username": self.admin.username, "password": "test-password-123"})
        self.assertRedirects(response, reverse("amfm:panel_beranda"))
        self.assertEqual(bagian_utama(self.admin), "amfm")
        self.client.logout()
        response = self.client.post(reverse("siwak:login_khusus"), {"username": self.admin.username, "password": "test-password-123"})
        self.assertRedirects(response, reverse("amfm:panel_beranda"))
        self.assertFalse(self.admin.is_staff)
        self.assertEqual(self.client.get(reverse("siwak:panel_beranda")).status_code, 403)

    def test_tamu_dan_salah_role_ditolak_di_semua_endpoint_sensitif(self):
        from django.urls import reverse
        endpoints = [
            ("panel_beranda", []), ("panel_daftar", []), ("panel_detail", [self.obj.pk]),
            ("panel_bukti", [self.obj.pk]), ("panel_keputusan", [self.obj.pk]),
            ("panel_hapus", [self.obj.pk]), ("panel_massal", []), ("panel_pengaturan", []),
        ]
        self.client.logout()
        for name, args in endpoints:
            url = reverse("amfm:"+name, args=args)
            self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.peserta)
        for name, args in endpoints:
            self.assertEqual(self.client.get(reverse("amfm:"+name, args=args)).status_code, 403)
        self.assertEqual(self.client.get(reverse("amfm:panel_login")).status_code, 403)

    def test_akses_baca_tidak_dapat_mutasi_atau_mengelola_pengaturan(self):
        from django.urls import reverse
        reader = get_user_model().objects.create_user(username="reader")
        reader.user_permissions.add(Permission.objects.get(content_type__app_label="amfm", codename="view_pendaftaran"))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse("amfm:panel_detail", args=[self.obj.pk])).status_code, 200)
        for name, args in [("panel_keputusan", [self.obj.pk]), ("panel_hapus", [self.obj.pk]), ("panel_pengaturan", []), ("panel_massal", []), ("panel_konten", [])]:
            self.assertEqual(self.client.post(reverse("amfm:"+name, args=args), {}).status_code, 403)

    def test_cari_filter_kedua_pilihan_dan_parameter_tidak_valid(self):
        from django.urls import reverse
        url = reverse("amfm:panel_daftar")
        for query in ({"q": "2600000001"}, {"birdept": self.itf.pk}, {"birdept": self.medkre.pk}, {"status": "menunggu"}, {"birdept": "rusak", "status": "asing", "page": "rusak"}):
            self.assertContains(self.client.get(url, query), self.obj.nama_lengkap)
        for query in ({"q": "tidak ditemukan"}, {"birdept": self.lain.pk}, {"status": "diterima"}):
            self.assertNotContains(self.client.get(url, query), self.obj.nama_lengkap)

    def test_keputusan_post_dan_filter_kembali_tetap_tersimpan(self):
        from django.urls import reverse
        url = reverse("amfm:panel_keputusan", args=[self.obj.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url, {"status": "diterima", "penempatan": self.lain.pk})
        self.assertEqual(response.status_code, 400)
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.status, "menunggu")
        response = self.client.post(url, {"status": "diterima", "penempatan": self.itf.pk, "next": "/amfm/admin/pendaftar/?status=menunggu"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response.url)
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.status, "diterima")
        self.assertEqual(self.obj.penempatan_id, self.itf.pk)

    def test_bulk_dengan_penempatan_dan_tanpa_konfirmasi(self):
        from django.urls import reverse
        url = reverse("amfm:panel_massal")
        data = {"ids": [self.obj.pk], "status": "diterima", "penempatan": self.itf.pk}
        self.client.post(url, data)
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.status, "menunggu")
        self.client.post(url, {**data, "konfirmasi": "on"})
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.status, "diterima")
        self.assertEqual(self.obj.penempatan_id, self.itf.pk)

    def test_statistik_menghitung_orang_dan_kedua_pilihan_tanpa_duplikasi_join(self):
        from .services.statistik import statistik_panel
        result = statistik_panel()
        self.assertEqual(result["total"], {"total": 1, "menunggu": 1, "diterima": 0, "ditolak": 0})
        counts = {row["obj"].pk: row["total"] for row in result["birdept"]}
        self.assertEqual(counts, {self.itf.pk: 1, self.medkre.pk: 1, self.lain.pk: 0})
        simpan_keputusan(self.obj.pk, "diterima", self.itf.pk)
        result = statistik_panel()
        self.assertEqual(result["total"]["diterima"], 1)
        self.assertEqual(result["total"]["menunggu"], 0)
        self.obj.delete()
        self.assertEqual(statistik_panel()["total"]["total"], 0)

    def test_pengaturan_memakai_validasi_jadwal_dan_sumber_formulir_publik(self):
        from django.urls import reverse
        from .models import AmfmInfo
        url = reverse("amfm:panel_pengaturan")
        data = {"status_pendaftaran": "dibuka", "dibuka_pada": "2026-10-30T10:00", "ditutup_pada": "2026-10-29T10:00"}
        self.assertContains(self.client.post(url, data), "Deadline harus setelah")
        response = self.client.post(url, {"status_pendaftaran": "ditutup", "guidebook_url": "https://example.com/guide", "kurikulum_url": "https://example.com/kurikulum"})
        self.assertEqual(response.status_code, 302)
        info = AmfmInfo.get_solo()
        self.assertEqual(info.status_saat_ini, "ditutup")
        self.assertEqual(info.guidebook_url, "https://example.com/guide")

    def test_konten_crud_dan_timeline_tanggal_terbalik(self):
        from django.urls import reverse
        from .models import AmfmBenefit, AmfmTimeline
        self.client.post(reverse("amfm:panel_konten_tambah", args=["benefit"]), {"judul": "Relasi", "deskripsi": "Belajar bersama", "urutan": 1})
        obj = AmfmBenefit.objects.get()
        self.assertContains(self.client.get(reverse("amfm:beranda")), "Relasi")
        self.client.post(reverse("amfm:panel_konten_ubah", args=["benefit", obj.pk]), {"judul": "Relasi baru", "deskripsi": "Belajar bersama", "urutan": 2})
        obj.refresh_from_db()
        self.assertEqual(obj.judul, "Relasi baru")
        self.client.post(reverse("amfm:panel_konten_hapus", args=["benefit", obj.pk]), {"konfirmasi": "ya"})
        self.assertFalse(AmfmBenefit.objects.exists())
        self.client.post(reverse("amfm:panel_konten_tambah", args=["timeline"]), {"judul": "Tahap", "tanggal_mulai": "2026-10-30", "tanggal_selesai": "2026-10-29"})
        self.assertFalse(AmfmTimeline.objects.exists())

    def test_hapus_memerlukan_post_konfirmasi_dan_tidak_menghapus_akun(self):
        from django.urls import reverse
        url = reverse("amfm:panel_hapus", args=[self.obj.pk])
        self.client.get(url)
        self.client.post(url, {})
        self.assertTrue(Pendaftaran.objects.filter(pk=self.obj.pk).exists())
        self.client.post(url, {"konfirmasi": "ya"})
        self.assertFalse(Pendaftaran.objects.filter(pk=self.obj.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.peserta.pk).exists())

    def test_bukti_terotorisasi_dan_tidak_menggunakan_url_storage(self):
        from django.urls import reverse
        from .test_pendaftaran import gambar
        self.obj.bukti_follow.save("bukti.png", gambar())
        response = self.client.get(reverse("amfm:panel_bukti", args=[self.obj.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))
        response = self.client.get(reverse("amfm:panel_detail", args=[self.obj.pk]))
        self.assertNotContains(response, self.obj.bukti_follow.name)
        self.client.force_login(self.peserta)
        self.assertEqual(self.client.get(reverse("amfm:panel_bukti", args=[self.obj.pk])).status_code, 403)

    def test_csrf_dan_redirect_eksternal(self):
        from django.test import Client
        from django.urls import reverse
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(reverse("amfm:panel_keputusan", args=[self.obj.pk]), {"status": "ditolak"}).status_code, 403)
        response = self.client.post(reverse("amfm:panel_massal"), {"next": "https://evil.example/"})
        self.assertEqual(response.url, reverse("amfm:panel_daftar"))

    def test_pagination_mempertahankan_filter(self):
        from django.urls import reverse
        for i in range(26):
            user = get_user_model().objects.create_user(username=f"pagination-{i}")
            Pendaftaran.objects.create(user=user, npm=f"2700000{i:03}", nama_lengkap=f"Peserta {i}", jurusan="IK", jenis_kelamin="L", id_line="id_line", pilihan_1=self.itf, pilihan_2=self.medkre, motivasi="Belajar")
        response = self.client.get(reverse("amfm:panel_daftar"), {"q": "Peserta", "birdept": self.itf.pk, "page": 2})
        self.assertEqual(response.context["halaman"].number, 2)
        self.assertContains(response, "q=Peserta")
        self.assertContains(response, "26.")

    def test_login_tanpa_izin_dan_next_eksternal(self):
        from django.urls import reverse
        self.client.logout()
        self.peserta.set_password("test-password-123")
        self.peserta.save()
        response = self.client.post(reverse("amfm:panel_login"), {"username": self.peserta.username, "password": "test-password-123"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.post(reverse("amfm:panel_login"), {"username": self.admin.username, "password": "test-password-123", "next": "https://evil.example/"})
        self.assertRedirects(response, reverse("amfm:panel_beranda"))

    def test_clarity_tidak_dimuat_di_login_admin_production(self):
        from django.urls import reverse
        self.client.logout()
        with self.settings(DEPLOY_ENV="production"):
            self.assertNotContains(self.client.get(reverse("amfm:panel_login")), "clarity.ms")

    def test_django_admin_validasi_penempatan_dan_bulk_tetap_sama(self):
        from django.urls import reverse
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib import admin
        from django.test import RequestFactory
        from .admin import PendaftaranAdmin
        self.admin.is_staff = True
        self.admin.save()
        response = self.client.get(reverse("admin:amfm_pendaftaran_change", args=[self.obj.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Penempatan Birdept")
        response = self.client.post(reverse("admin:amfm_pendaftaran_change", args=[self.obj.pk]), {"status": "diterima", "penempatan": self.itf.pk, "_save": "Simpan"})
        self.assertEqual(response.status_code, 302)
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.status, "diterima")
        self.assertEqual(self.obj.penempatan_id, self.itf.pk)
        request = RequestFactory().post("/admin/")
        request.user = self.admin
        request.session = {}
        request._messages = FallbackStorage(request)
        PendaftaranAdmin(Pendaftaran, admin.site).tolak(request, Pendaftaran.objects.filter(pk=self.obj.pk))
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.status, "ditolak")
        self.assertIsNone(self.obj.penempatan)
