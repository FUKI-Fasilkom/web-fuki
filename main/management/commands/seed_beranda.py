"""Isi beranda dengan kegiatan contoh supaya tata letaknya bisa dilihat utuh.

Contoh pemakaian:

    # isi konten contoh
    python manage.py seed_beranda

    # bersihkan lagi setelah selesai melihat-lihat
    python manage.py seed_beranda --clear

Dipakai saat pengembangan: tanpa kegiatan mendatang, section "Upcoming Event"
hanya menampilkan kalimat "Belum ada kegiatan..." sehingga desainnya sulit
dinilai. Section beranda lainnya tidak membaca database, jadi tidak perlu diisi.

Aman dijalankan berulang kali. Seluruh baris yang dibuat di sini diberi awalan
judul PREFIX, dan hanya baris berawalan itu yang dihapus oleh --clear --
kegiatan asli yang diisi pengurus lewat admin tidak akan pernah tersentuh.
"""

import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from kegiatan.models import Kegiatan

PREFIX = "[Contoh]"

LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua."
)


class Command(BaseCommand):
    help = "Isi (atau bersihkan) kegiatan contoh untuk beranda."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Hapus kegiatan contoh yang pernah dibuat perintah ini, lalu berhenti.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["clear"]:
            self.bersihkan()
            return
        self.isi()

    def bersihkan(self):
        jumlah, _ = Kegiatan.objects.filter(judul__startswith=PREFIX).delete()
        self.stdout.write(self.style.SUCCESS(f"Kegiatan: {jumlah} baris contoh dihapus."))

    def isi(self):
        # Satu kegiatan per kategori, semuanya bertanggal mendatang, supaya
        # keempat tab filter di beranda punya isi untuk dibuktikan.
        hari_ini = datetime.date.today()
        for i, (kategori, label) in enumerate(Kegiatan.KATEGORI_CHOICES):
            judul = f"{PREFIX} {label}"
            _, dibuat = Kegiatan.objects.get_or_create(judul=judul, defaults={
                "deskripsi": LOREM,
                "kategori": kategori,
                "tanggal": hari_ini + datetime.timedelta(days=7 + i),
                "start_time": datetime.time(7, 0),
                "end_time": datetime.time(15, 0),
                "lokasi": "Auditorium Fasilkom UI",
                "guest_star": "Ustadz Fulan",
                "contact": "0812-0000-0000",
            })
            if dibuat:
                self.stdout.write(f"Kegiatan: {judul}")

        self.stdout.write(self.style.SUCCESS(
            "Selesai. Jalankan 'manage.py seed_beranda --clear' untuk menghapusnya lagi."
        ))
