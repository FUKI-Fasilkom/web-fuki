from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Pendaftaran


@receiver(post_delete, sender=Pendaftaran)
def hapus_bukti(sender, instance, **kwargs):
    file = instance.bukti_follow
    if file.name:
        transaction.on_commit(lambda: file.storage.delete(file.name))
