from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Pendaftaran


@receiver(post_delete, sender=Pendaftaran)
def hapus_bukti(sender, instance, **kwargs):
    for file in (instance.bukti_follow, instance.bukti_follow_2):
        if file.name:
            transaction.on_commit(lambda storage=file.storage, name=file.name: storage.delete(name))
