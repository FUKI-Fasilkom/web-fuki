"""Membuat `EventRSVP` dan memindahkan RSVP tertunda (`RSVPTertunda`) menjadi RSVP sungguhan."""

from django.db import transaction

from ..models import EventRSVP, RSVPTertunda


@transaction.atomic
def buat_rsvp(*, event, user, kehadiran, alasan_izin="", qr_registrasi_token=None,
              qr_kupon_token=None, dikirim_pada=None):
    """Buat `EventRSVP` persis seperti `rsvp_event` menyimpannya di web.

    Token, `status_kehadiran` (belum_hadir), dan `status_kupon` (unused) memakai
    default model; token hanya diteruskan kalau sudah pernah dibuat (RSVP tertunda).
    """
    rsvp = EventRSVP(event=event, user=user, kehadiran=kehadiran, alasan_izin=alasan_izin)
    if qr_registrasi_token:
        rsvp.qr_registrasi_token = qr_registrasi_token
    if qr_kupon_token:
        rsvp.qr_kupon_token = qr_kupon_token
    rsvp.save()
    if dikirim_pada:
        # created_at auto_now_add: hanya bisa ditimpa lewat update().
        EventRSVP.objects.filter(pk=rsvp.pk).update(created_at=dikirim_pada)
        rsvp.created_at = dikirim_pada
    return rsvp


@transaction.atomic
def klaim_rsvp_tertunda(profile):
    """Ubah semua RSVP tertunda milik `profile` jadi `EventRSVP` untuk `profile.user`.

    Dipanggil setelah profil diklaim akun login. Kalau akun itu sudah punya RSVP
    untuk event yang sama, yang sudah ada dibiarkan (bisa saja sudah check-in) dan
    yang tertunda dibuang. Mengembalikan jumlah RSVP yang dibuat.
    """
    if profile.user_id is None:
        return 0

    dibuat = 0
    for tertunda in RSVPTertunda.objects.filter(profile=profile).select_related("event"):
        if not EventRSVP.objects.filter(event=tertunda.event, user_id=profile.user_id).exists():
            buat_rsvp(
                event=tertunda.event,
                user=profile.user,
                kehadiran=tertunda.kehadiran,
                alasan_izin=tertunda.alasan_izin,
                qr_registrasi_token=tertunda.qr_registrasi_token,
                qr_kupon_token=tertunda.qr_kupon_token,
                dikirim_pada=tertunda.dikirim_pada,
            )
            dibuat += 1
        tertunda.delete()
    return dibuat
