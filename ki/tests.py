"""Tes panel Kontrol Internal (/ki/admin/)."""

import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from birdep.models import BirDep
from kegiatan.models import Kegiatan

User = get_user_model()


def akun_ki(username="ki-angga", **extra):
    """Akun pengurus KI: bukan staf, hanya pemegang izin ubah Kegiatan."""
    user = User.objects.create_user(username=username, password="rahasia123", **extra)
    user.user_permissions.add(Permission.objects.get(codename="change_kegiatan"))
    return user


def buat_kegiatan(judul="Kajian Rutin", **extra):
    extra.setdefault("tanggal", datetime.date.today() + datetime.timedelta(days=7))
    return Kegiatan.objects.create(judul=judul, **extra)


class AksesPanelKiTests(TestCase):
    def test_anonim_diarahkan_ke_login_akun_khusus(self):
        response = self.client.get(reverse("ki:panel_daftar"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("siwak:login_khusus"), response["Location"])

    def test_akun_tanpa_izin_dapat_halaman_akses_ditolak(self):
        User.objects.create_user(username="mentee-biasa", password="rahasia123")
        self.client.login(username="mentee-biasa", password="rahasia123")
        response = self.client.get(reverse("ki:panel_daftar"))
        self.assertEqual(response.status_code, 403)
        # Halaman 403 bersama, bukan HttpResponseForbidden polos.
        self.assertTemplateUsed(response, "siwak/akses_ditolak.html")
        self.assertContains(response, "Admin Panel Kontrol Internal", status_code=403)

    def test_pengurus_ki_boleh_masuk(self):
        akun_ki()
        self.client.login(username="ki-angga", password="rahasia123")
        self.assertEqual(self.client.get(reverse("ki:panel_daftar")).status_code, 200)

    def test_superuser_boleh_masuk(self):
        User.objects.create_superuser(username="root", password="rahasia123")
        self.client.login(username="root", password="rahasia123")
        self.assertEqual(self.client.get(reverse("ki:panel_daftar")).status_code, 200)

    def test_pengurus_ki_tidak_bisa_membuka_panel_siwak(self):
        """Pemisahan yang jadi alasan panel ini tidak memakai is_staff."""
        akun_ki()
        self.client.login(username="ki-angga", password="rahasia123")
        self.assertEqual(self.client.get(reverse("siwak:panel_beranda")).status_code, 403)

    def test_pengurus_siwak_tidak_otomatis_bisa_membuka_panel_ki(self):
        User.objects.create_user(username="staf-siwak", password="rahasia123", is_staff=True)
        self.client.login(username="staf-siwak", password="rahasia123")
        self.assertEqual(self.client.get(reverse("ki:panel_daftar")).status_code, 403)

    def test_semua_alamat_panel_dijaga(self):
        kegiatan = buat_kegiatan()
        User.objects.create_user(username="orang-luar", password="rahasia123")
        self.client.login(username="orang-luar", password="rahasia123")
        for url in [
            reverse("ki:panel_daftar"),
            reverse("ki:panel_tambah"),
            reverse("ki:panel_ubah", args=[kegiatan.pk]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("ki:panel_hapus", args=[kegiatan.pk])).status_code, 403
        )

    def test_pengurus_ki_boleh_login_lewat_akun_khusus(self):
        """Akun KI bukan staf, jadi pintu inilah satu-satunya jalan masuknya."""
        akun_ki()
        response = self.client.post(
            reverse("siwak:login_khusus"),
            {"username": "ki-angga", "password": "rahasia123"},
        )
        self.assertEqual(response.status_code, 302)
        # Tujuan setelah login diatur satu tempat: akses.bagian_utama.
        self.assertEqual(response["Location"], reverse("ki:panel_daftar"))


class DaftarKegiatanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.syitif = BirDep.objects.create(nama="SyiTif", logo_filename="Logo-SyiTif.png")
        cls.sosmas = BirDep.objects.create(nama="SosMas", logo_filename="Logo-SosMas.png")
        cls.kajian = buat_kegiatan(
            judul="Kajian Jumat", kategori="kajian",
            tanggal=datetime.date(2026, 3, 1),
            start_time=datetime.time(13), end_time=datetime.time(15),
            lokasi="Auditorium Fasilkom UI",
            link_registrasi="https://contoh.test/daftar",
        )
        cls.bakti = buat_kegiatan(
            judul="Bakti Sosial", kategori="sosial",
            tanggal=datetime.date(2026, 4, 1),
            tipe=Kegiatan.TIPE_BIRDEP, birdep=cls.sosmas,
        )
        cls.maba = buat_kegiatan(
            judul="Welcoming Maba", kategori="maba",
            tanggal=datetime.date(2026, 5, 1), tipe=Kegiatan.TIPE_SIWAK,
        )

    def setUp(self):
        akun_ki()
        self.client.login(username="ki-angga", password="rahasia123")

    def test_hanya_satu_menu_di_panel(self):
        response = self.client.get(reverse("ki:panel_daftar"))
        self.assertEqual(len(response.context["menu"]), 1)
        butir = response.context["menu"][0]["butir"]
        self.assertEqual([b["label"] for b in butir], ["Kegiatan"])
        self.assertEqual(response.context["panel_nama"], "Panel Kontrol Internal")

    def test_memakai_templat_dan_kerangka_panel_siwak(self):
        """Yang dimaksud "reuse UI": templat yang sama, bukan markup yang disalin."""
        response = self.client.get(reverse("ki:panel_daftar"))
        self.assertTemplateUsed(response, "siwak/panel/base.html")
        self.assertTemplateUsed(response, "siwak/panel/daftar.html")
        self.assertTemplateUsed(response, "siwak/panel/_sel.html")
        self.assertTemplateUsed(response, "siwak/panel/_menu.html")
        # Tidak boleh ada jejak panel SIWAK di panel KI.
        self.assertNotContains(response, "Panel SIWAK-NG")
        self.assertNotContains(response, reverse("siwak:panel_beranda"))

    def test_daftar_memuat_semua_kegiatan(self):
        response = self.client.get(reverse("ki:panel_daftar"))
        for kegiatan in (self.kajian, self.bakti, self.maba):
            self.assertContains(response, kegiatan.judul)
        self.assertContains(response, "13.00 - 15.00")
        self.assertContains(response, "Auditorium Fasilkom UI")
        # Kolom penyelenggara menyebut nama BirDep-nya, bukan kata "Biro / Departemen".
        self.assertContains(response, "SosMas")

    def test_pencarian(self):
        response = self.client.get(reverse("ki:panel_daftar"), {"q": "bakti"})
        self.assertContains(response, "Bakti Sosial")
        self.assertNotContains(response, "Kajian Jumat")

    def test_pencarian_juga_menjangkau_nama_birdep(self):
        response = self.client.get(reverse("ki:panel_daftar"), {"q": "sosmas"})
        self.assertContains(response, "Bakti Sosial")
        self.assertNotContains(response, "Welcoming Maba")

    def test_saringan_kategori_tipe_dan_birdep(self):
        for params, ada, tiada in [
            ({"kategori": "sosial"}, "Bakti Sosial", "Kajian Jumat"),
            ({"tipe": Kegiatan.TIPE_SIWAK}, "Welcoming Maba", "Kajian Jumat"),
            ({"birdep": self.sosmas.pk}, "Bakti Sosial", "Welcoming Maba"),
        ]:
            with self.subTest(params=params):
                response = self.client.get(reverse("ki:panel_daftar"), params)
                self.assertContains(response, ada)
                self.assertNotContains(response, tiada)
                self.assertTrue(response.context["ada_saringan"])

    def test_saringan_ngawur_diabaikan(self):
        """Nilai yang bukan pilihan tidak boleh sampai ke query."""
        response = self.client.get(reverse("ki:panel_daftar"), {"kategori": "bukan-kategori"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kajian Jumat")
        self.assertFalse(response.context["ada_saringan"])

    def test_pengurutan_judul_dua_arah(self):
        urut = lambda **p: [  # noqa: E731
            b["obj"].judul
            for b in self.client.get(reverse("ki:panel_daftar"), p).context["baris"]
        ]
        self.assertEqual(urut(urut="judul"), ["Bakti Sosial", "Kajian Jumat", "Welcoming Maba"])
        self.assertEqual(
            urut(urut="judul", arah="turun"), ["Welcoming Maba", "Kajian Jumat", "Bakti Sosial"]
        )

    def test_urutan_awal_menurut_tanggal(self):
        response = self.client.get(reverse("ki:panel_daftar"))
        self.assertEqual(response.context["kunci_urut"], "tanggal")
        self.assertEqual(
            [b["obj"].pk for b in response.context["baris"]],
            [self.kajian.pk, self.bakti.pk, self.maba.pk],
        )

    def test_pencarian_tidak_menghapus_urutan(self):
        response = self.client.get(reverse("ki:panel_daftar"), {"q": "a", "urut": "judul"})
        self.assertEqual(response.context["kunci_urut"], "judul")

    def test_keadaan_kosong(self):
        Kegiatan.objects.all().delete()
        response = self.client.get(reverse("ki:panel_daftar"))
        self.assertContains(response, "Belum ada kegiatan yang didaftarkan.")


class FormKegiatanTests(TestCase):
    def setUp(self):
        akun_ki()
        self.client.login(username="ki-angga", password="rahasia123")
        self.birdep = BirDep.objects.create(nama="SyiTif", logo_filename="Logo-SyiTif.png")

    def isi_minimal(self, **extra):
        data = {
            "judul": "Kegiatan Baru",
            "deskripsi": "",
            "kategori": "kajian",
            "tipe": Kegiatan.TIPE_FUKI,
            "birdep": "",
            "tanggal": "2026-06-01",
            "start_time": "",
            "end_time": "",
            "lokasi": "",
            "link_lokasi": "",
            "contact": "",
            "link_registrasi": "",
        }
        data.update(extra)
        return data

    def test_field_form_sama_dengan_django_admin(self):
        """Django admin tidak membatasi `fields`, jadi acuannya seluruh field
        model yang bisa disunting — tanpa `gambar`/`guest_star` yang sudah dihapus."""
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        permintaan = RequestFactory().get("/admin/")
        permintaan.user = User.objects.create_superuser(username="root", password="rahasia123")
        admin_form = django_admin.site._registry[Kegiatan].get_form(permintaan)()

        panel_form = self.client.get(reverse("ki:panel_tambah")).context["form"]
        self.assertEqual(list(panel_form.fields), list(admin_form.fields))

    def test_tambah_kegiatan_tanpa_field_opsional(self):
        response = self.client.post(reverse("ki:panel_tambah"), self.isi_minimal())
        self.assertRedirects(response, reverse("ki:panel_daftar"))
        kegiatan = Kegiatan.objects.get(judul="Kegiatan Baru")
        self.assertIsNone(kegiatan.start_time)
        self.assertEqual(kegiatan.lokasi, "")

    def test_tambah_kegiatan_lengkap(self):
        self.client.post(reverse("ki:panel_tambah"), self.isi_minimal(
            judul="Kajian Akbar",
            start_time="13:00", end_time="15:30",
            lokasi="Auditorium", contact="0812-0000-0000",
            link_registrasi="https://contoh.test/daftar",
        ))
        kegiatan = Kegiatan.objects.get(judul="Kajian Akbar")
        self.assertEqual(kegiatan.start_time, datetime.time(13, 0))
        self.assertEqual(kegiatan.end_time, datetime.time(15, 30))
        self.assertEqual(kegiatan.contact, "0812-0000-0000")

    def test_tipe_birdep_wajib_memilih_birdep(self):
        response = self.client.post(
            reverse("ki:panel_tambah"), self.isi_minimal(tipe=Kegiatan.TIPE_BIRDEP)
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Kegiatan.objects.exists())
        self.assertFormError(
            response.context["form"], "birdep", "Pilih Biro / Departemen penyelenggaranya."
        )

    def test_tipe_birdep_dengan_birdep_tersimpan(self):
        self.client.post(reverse("ki:panel_tambah"), self.isi_minimal(
            tipe=Kegiatan.TIPE_BIRDEP, birdep=self.birdep.pk
        ))
        self.assertEqual(Kegiatan.objects.get().birdep, self.birdep)

    def test_birdep_nonaktif_tidak_jadi_pilihan(self):
        BirDep.objects.create(nama="Bubar", logo_filename="", is_active=False)
        form = self.client.get(reverse("ki:panel_tambah")).context["form"]
        self.assertNotIn("Bubar", [str(b) for b in form.fields["birdep"].queryset])

    def test_ubah_kegiatan(self):
        kegiatan = buat_kegiatan(judul="Judul Lama", lokasi="Ruang A")
        response = self.client.post(
            reverse("ki:panel_ubah", args=[kegiatan.pk]),
            self.isi_minimal(judul="Judul Baru", lokasi="Ruang B"),
        )
        self.assertRedirects(response, reverse("ki:panel_daftar"))
        kegiatan.refresh_from_db()
        self.assertEqual(kegiatan.judul, "Judul Baru")
        self.assertEqual(kegiatan.lokasi, "Ruang B")

    def test_simpan_dan_lanjut_ubah_kembali_ke_form_objek_itu(self):
        response = self.client.post(
            reverse("ki:panel_tambah"), self.isi_minimal(_continue="1")
        )
        kegiatan = Kegiatan.objects.get(judul="Kegiatan Baru")
        self.assertRedirects(response, reverse("ki:panel_ubah", args=[kegiatan.pk]))

    def test_simpan_dan_lanjut_ubah_dari_halaman_ubah(self):
        kegiatan = buat_kegiatan(judul="Judul Lama")
        url = reverse("ki:panel_ubah", args=[kegiatan.pk])
        response = self.client.post(url, self.isi_minimal(judul="Judul Baru", _continue="1"))
        self.assertRedirects(response, url)
        kegiatan.refresh_from_db()
        self.assertEqual(kegiatan.judul, "Judul Baru")

    def test_simpan_dan_tambah_lagi_kembali_ke_form_kosong(self):
        response = self.client.post(
            reverse("ki:panel_tambah"), self.isi_minimal(_addanother="1")
        )
        self.assertRedirects(response, reverse("ki:panel_tambah"))
        self.assertTrue(Kegiatan.objects.filter(judul="Kegiatan Baru").exists())

    def test_tombol_simpan_tambahan_hanya_di_panel_ki(self):
        """Templat form-nya dipakai bersama SIWAK, jadi tombolnya digerbangi konteks."""
        response = self.client.get(reverse("ki:panel_tambah"))
        self.assertTrue(response.context["simpan_lanjutan"])
        self.assertContains(response, 'name="_continue"')
        self.assertContains(response, 'name="_addanother"')

    def test_form_ubah_memuat_tombol_hapus(self):
        kegiatan = buat_kegiatan()
        response = self.client.get(reverse("ki:panel_ubah", args=[kegiatan.pk]))
        self.assertEqual(
            response.context["url_hapus"], reverse("ki:panel_hapus", args=[kegiatan.pk])
        )

    def test_form_tambah_tanpa_tombol_hapus(self):
        self.assertEqual(self.client.get(reverse("ki:panel_tambah")).context["url_hapus"], "")

    def test_hapus_kegiatan(self):
        kegiatan = buat_kegiatan()
        response = self.client.post(reverse("ki:panel_hapus", args=[kegiatan.pk]))
        self.assertRedirects(response, reverse("ki:panel_daftar"))
        self.assertFalse(Kegiatan.objects.filter(pk=kegiatan.pk).exists())

    def test_hapus_hanya_lewat_post(self):
        kegiatan = buat_kegiatan()
        self.assertEqual(
            self.client.get(reverse("ki:panel_hapus", args=[kegiatan.pk])).status_code, 405
        )
        self.assertTrue(Kegiatan.objects.filter(pk=kegiatan.pk).exists())

    def test_perubahan_panel_langsung_tampil_di_halaman_publik(self):
        self.client.post(reverse("ki:panel_tambah"), self.isi_minimal(
            judul="Kajian Dari Panel KI", lokasi="Auditorium",
        ))
        publik = self.client.get(reverse("kegiatan:home"))
        self.assertContains(publik, "Kajian Dari Panel KI")
