"""Signal untuk inisialisasi mentoring, akun mentor lokal, dan pembersihan file."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Answer, GaleriFoto, KelompokMentoring, MentoringSession, Profile


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


@receiver(post_delete, sender=Profile, dispatch_uid="siwak.hapus_akun_lokal")
def hapus_akun_lokal(sender, instance, using, **kwargs):
    """Akun login mentor non-SSO ikut terhapus bersama profilnya.

    `Profile.user` adalah OneToOne: menghapus User menghapus profil, tapi tidak
    sebaliknya. Tanpa ini, menghapus mentor dari panel menyisakan User yang
    masih bisa login — lalu mentok di `require_mentor` dengan 403 yang
    membingungkan. Akun SSO tidak disentuh: barisnya milik SSO UI, bukan milik
    panel.
    """
    if instance.auth_source != Profile.SOURCE_LOKAL or not instance.user_id:
        return

    user_id = instance.user_id
    User = get_user_model()

    def hapus_setelah_commit():
        # Dicek ulang, bukan dihapus langsung: kalau justru User yang dihapus
        # lebih dulu (profil ikut lewat CASCADE), barisnya sudah tidak ada di
        # sini dan panggilan ini tidak boleh berubah jadi rekursi.
        User.objects.using(using).filter(pk=user_id, profil__isnull=True).delete()

    transaction.on_commit(hapus_setelah_commit, using=using, robust=True)


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
    """Jangan hapus file yang masih dipakai jawaban lain."""
    if name and not Answer.objects.using(using).filter(file_answer=name).exists():
        storage.delete(name)


@receiver(pre_save, sender=Answer)
def remember_replaced_tugas_file(sender, instance, using, raw=False, update_fields=None, **kwargs):
    instance._old_tugas_file = None
    field = "file_answer"
    if raw or not instance.pk or (update_fields is not None and field not in update_fields):
        return
    previous = sender.objects.using(using).filter(pk=instance.pk).first()
    old_file = getattr(previous, field, None)
    new_file = getattr(instance, field)
    if old_file and (old_file.name != new_file.name or not new_file._committed):
        instance._old_tugas_file = (old_file.storage, old_file.name)


@receiver(post_save, sender=Answer)
def delete_replaced_tugas_file(sender, instance, using, raw=False, **kwargs):
    previous = getattr(instance, "_old_tugas_file", None)
    if not raw and previous:
        storage, name = previous
        transaction.on_commit(
            lambda: delete_unused_tugas_file(storage, name, using), using=using, robust=True
        )
    instance._old_tugas_file = None


@receiver(post_delete, sender=Answer)
def delete_tugas_file(sender, instance, using, **kwargs):
    file = instance.file_answer
    if file:
        storage, name = file.storage, file.name
        transaction.on_commit(
            lambda: delete_unused_tugas_file(storage, name, using), using=using, robust=True
        )
