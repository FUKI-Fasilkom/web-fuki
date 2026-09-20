"""Signal untuk inisialisasi mentoring dan pembersihan file galeri/tugas."""

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Answer, GaleriFoto, KelompokMentoring, MentoringSession, TugasSubmission


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


def delete_unused_tugas_file(storage, name, using):
    """Periksa kedua pemilik file sebelum menghapus objek dari storage."""
    if name and not (
        TugasSubmission.objects.using(using).filter(file=name).exists()
        or Answer.objects.using(using).filter(file_answer=name).exists()
    ):
        storage.delete(name)


@receiver(pre_save, sender=TugasSubmission)
@receiver(pre_save, sender=Answer)
def remember_replaced_tugas_file(sender, instance, using, raw=False, update_fields=None, **kwargs):
    instance._old_tugas_file = None
    field = "file" if sender is TugasSubmission else "file_answer"
    if raw or not instance.pk or (update_fields is not None and field not in update_fields):
        return
    previous = sender.objects.using(using).filter(pk=instance.pk).first()
    old_file = getattr(previous, field, None)
    new_file = getattr(instance, field)
    if old_file and (old_file.name != new_file.name or not new_file._committed):
        instance._old_tugas_file = (old_file.storage, old_file.name)


@receiver(post_save, sender=TugasSubmission)
@receiver(post_save, sender=Answer)
def delete_replaced_tugas_file(sender, instance, using, raw=False, **kwargs):
    previous = getattr(instance, "_old_tugas_file", None)
    if not raw and previous:
        storage, name = previous
        transaction.on_commit(
            lambda: delete_unused_tugas_file(storage, name, using), using=using, robust=True
        )
    instance._old_tugas_file = None


@receiver(post_delete, sender=TugasSubmission)
@receiver(post_delete, sender=Answer)
def delete_tugas_file(sender, instance, using, **kwargs):
    file = instance.file if sender is TugasSubmission else instance.file_answer
    if file:
        storage, name = file.storage, file.name
        transaction.on_commit(
            lambda: delete_unused_tugas_file(storage, name, using), using=using, robust=True
        )
