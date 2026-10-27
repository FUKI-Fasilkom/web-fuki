"""Aturan keputusan yang sama untuk panel AMFM dan Django admin."""
from django.core.exceptions import ValidationError
from django.db import transaction

from amfm.models import Pendaftaran

STATUS = dict(Pendaftaran._meta.get_field("status").choices)


def validasi_keputusan(pendaftaran, status, penempatan_id):
    if status not in STATUS:
        raise ValidationError("Status penerimaan tidak dikenal.")
    if status == "diterima":
        if not penempatan_id:
            raise ValidationError("Pendaftar diterima wajib memiliki penempatan birdept.")
        if penempatan_id not in (pendaftaran.pilihan_1_id, pendaftaran.pilihan_2_id):
            raise ValidationError("Penempatan harus salah satu dari dua pilihan peserta.")
        return penempatan_id
    return None


@transaction.atomic
def simpan_keputusan(pk, status, penempatan_id):
    obj = Pendaftaran.objects.select_for_update().get(pk=pk)
    obj.penempatan_id = validasi_keputusan(obj, status, penempatan_id)
    obj.status = status
    obj.save(update_fields=["status", "penempatan"])
    return obj


@transaction.atomic
def ubah_status_massal(ids, status, penempatan_id=None):
    # Validasi seluruh pilihan sebelum menulis satu pun perubahan. Batch tidak
    # boleh berhasil sebagian, atau mengambil baris di luar pilihan pengguna.
    ids = set(ids)
    if not ids or len(ids) > 250:
        raise ValidationError("Pilih antara 1 dan 250 pendaftar.")
    rows = list(Pendaftaran.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    if len(rows) != len(ids):
        raise ValidationError("Sebagian data telah dihapus. Muat ulang daftar pendaftar.")
    for row in rows:
        try:
            row.penempatan_id = validasi_keputusan(row, status, penempatan_id or row.penempatan_id)
        except ValidationError as error:
            raise ValidationError(f"{row.nama_lengkap}: {error.messages[0]} Buka detail untuk mengatur penempatan.") from error
        row.status = status
    Pendaftaran.objects.bulk_update(rows, ["status", "penempatan"])
    return len(rows)
