from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import KelompokMentoring, MentoringSession


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
