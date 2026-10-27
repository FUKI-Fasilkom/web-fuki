"""Kontrak seleksi, akses panel, statistik, dan pengelolaan AMFM."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase

from birdep.models import BirDep
from .models import Pendaftaran
from .panel_forms import KeputusanForm
from .services.seleksi import simpan_keputusan, ubah_status_massal


class SeleksiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.itf = BirDep.objects.create(nama="ITF", logo_filename="")
        cls.medkre = BirDep.objects.create(nama="Medkre", logo_filename="")
        cls.lain = BirDep.objects.create(nama="PSDM", logo_filename="")
        cls.peserta = get_user_model().objects.create_user(username="peserta-amfm")
        cls.obj = Pendaftaran.objects.create(
            user=cls.peserta, npm="2600000001", nama_lengkap="Peserta AMFM", jurusan="IK",
            jenis_kelamin="L", kontak="kontak", pilihan_1=cls.itf, pilihan_2=cls.medkre, motivasi="Belajar",
        )

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
            kontak="kontak", pilihan_1=self.itf, pilihan_2=self.medkre,
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
