"""Regression checks for gallery file deletion without contacting S3."""

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.test import TestCase, override_settings

from .models import GaleriFoto


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
})
class GalleryStorageDeletionTests(TestCase):
    def make_photo(self, filename="photo.png"):
        name = default_storage.save(f"siwak/galeri/{filename}", ContentFile(b"image"))
        return GaleriFoto.objects.create(gambar=name, caption="Storage test")

    def test_delete_removes_file_only_after_commit(self):
        photo = self.make_photo()
        name = photo.gambar.name
        pk = photo.pk
        with self.captureOnCommitCallbacks(execute=True):
            photo.delete()
            self.assertFalse(GaleriFoto.objects.filter(pk=pk).exists())
            self.assertTrue(default_storage.exists(name))
        self.assertFalse(default_storage.exists(name))

    def test_bulk_delete_removes_files(self):
        photos = [self.make_photo("first.png"), self.make_photo("second.png")]
        names = [photo.gambar.name for photo in photos]
        with self.captureOnCommitCallbacks(execute=True):
            GaleriFoto.objects.filter(pk__in=[photo.pk for photo in photos]).delete()
        for name in names:
            self.assertFalse(default_storage.exists(name))

    def test_rollback_preserves_file_and_record(self):
        photo = self.make_photo()
        name = photo.gambar.name
        pk = photo.pk
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    photo.delete()
                    raise RuntimeError("Abort deletion")
        self.assertEqual(callbacks, [])
        self.assertTrue(GaleriFoto.objects.filter(pk=pk).exists())
        self.assertTrue(default_storage.exists(name))

    def test_shared_file_is_kept_until_last_photo_is_deleted(self):
        photo = self.make_photo()
        name = photo.gambar.name
        other = GaleriFoto.objects.create(gambar=name)
        with self.captureOnCommitCallbacks(execute=True):
            photo.delete()
        self.assertTrue(default_storage.exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            other.delete()
        self.assertFalse(default_storage.exists(name))
