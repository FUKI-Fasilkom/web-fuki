"""Signal untuk inisialisasi data mentoring dan pembersihan file galeri."""

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import GaleriFoto, KelompokMentoring, MentoringSession


@receiver(post_save, sender=KelompokMentoring)
def create_fixed_mentoring_sessions(sender, instance, created, **kwargs):
    """Every mentoring group always starts with the four fixed session slots."""
    if not created:
        return

    MentoringSession.objects.bulk_create(
        [
            MentoringSession(
                kelompok=instance,
                nomor=number,
                judul=f"Sesi Mentoring {number}",
            )
            for number in range(1, 5)
        ]
    )


@receiver(post_delete, sender=GaleriFoto, dispatch_uid="siwak.hapus_file_galeri")
def hapus_file_galeri(sender, instance, using, **kwargs):
    if not instance.gambar:
        return

    storage = instance.gambar.storage
    nama = instance.gambar.name

    def hapus_setelah_commit():
        # Jangan hapus file yang masih dipakai foto galeri lain.
        if not sender.objects.using(using).filter(gambar=nama).exists():
            storage.delete(nama)

    # Rollback database harus tetap menyisakan file. Kegagalan storage dicatat
    # oleh Django tanpa menggagalkan callback lain setelah commit.
    transaction.on_commit(hapus_setelah_commit, using=using, robust=True)
