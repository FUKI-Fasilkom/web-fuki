from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from .models import Pendaftaran


@override_settings(DEBUG=True, AWS_STORAGE_BUCKET_NAME=None)
class SeedPendaftarTests(TestCase):
    def seed(self, jumlah=3):
        call_command("seed_amfm_pendaftar", jumlah=jumlah, stdout=StringIO())

    def test_data_demo_lengkap_aman_diulang_dan_tidak_menimpa_keputusan(self):
        self.seed()
        self.assertEqual(Pendaftaran.objects.count(), 3)
        self.assertEqual(set(Pendaftaran.objects.values_list("status", flat=True)), {"menunggu", "diterima", "ditolak"})
        obj = Pendaftaran.objects.get(status="menunggu")
        file_name = obj.bukti_follow.name
        self.assertTrue(obj.bukti_follow.storage.exists(file_name))
        obj.status = "ditolak"
        obj.save()
        self.seed()
        obj.refresh_from_db()
        self.assertEqual(Pendaftaran.objects.count(), 3)
        self.assertEqual(obj.status, "ditolak")
        self.assertEqual(obj.bukti_follow.name, file_name)
        self.assertFalse(obj.user.has_usable_password())
        self.assertFalse(obj.user.is_active)
        self.seed(4)
        self.assertEqual(Pendaftaran.objects.count(), 4)

    def test_akun_dengan_nama_sama_tidak_diambil_alih(self):
        user = get_user_model().objects.create_user(username="demo-amfm-001")
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(Pendaftaran.objects.count(), 0)
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_production_cloud_storage_dan_jumlah_tidak_valid_ditolak(self):
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            self.seed()
        with override_settings(AWS_STORAGE_BUCKET_NAME="bucket"), self.assertRaises(CommandError):
            self.seed()
        for jumlah in (0, 101):
            with self.assertRaises(CommandError):
                self.seed(jumlah)
        self.assertFalse(Pendaftaran.objects.exists())
