"""Isi beranda dengan konten contoh supaya tata letaknya bisa dilihat utuh.

Contoh pemakaian:

    # isi konten contoh
    python manage.py seed_beranda

    # bersihkan lagi setelah selesai melihat-lihat
    python manage.py seed_beranda --clear

Dipakai saat pengembangan: tanpa isi apa pun, tiap section beranda hanya
menampilkan kalimat "belum ada ..." sehingga desainnya sulit dinilai.

Aman dijalankan berulang kali. Seluruh baris yang dibuat di sini diberi awalan
judul PREFIX, dan hanya baris berawalan itu yang dihapus oleh --clear --
konten asli yang diisi pengurus lewat admin tidak akan pernah tersentuh.
"""

import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from kegiatan.models import Kegiatan
from main.models import Activity, CompanyProfile, Podcast, TentangFuki, TentangFukiGambar

PREFIX = "[Contoh]"

LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua."
)


class Command(BaseCommand):
    help = "Isi (atau bersihkan) konten contoh untuk beranda."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Hapus konten contoh yang pernah dibuat perintah ini, lalu berhenti.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["clear"]:
            self.bersihkan()
            return
        self.isi()

    def bersihkan(self):
        for model in (Kegiatan, Activity, Podcast, CompanyProfile):
            jumlah, _ = model.objects.filter(judul__startswith=PREFIX).delete()
            self.stdout.write(f"{model.__name__}: {jumlah} baris contoh dihapus")

        jumlah, _ = TentangFukiGambar.objects.filter(alt__startswith=PREFIX).delete()
        self.stdout.write(f"TentangFukiGambar: {jumlah} baris contoh dihapus")
        self.stdout.write(self.style.SUCCESS("Konten contoh dibersihkan."))

    def isi(self):
        tentang = TentangFuki.get_solo()
        if not tentang.deskripsi:
            tentang.deskripsi = (
                "Fuki adalah wadah untuk mempererat ukhuwah dan meningkatkan kualitas "
                "Islam agar dapat menjadi muslim yang bermanfaat bagi sekitar."
            )
            tentang.save()
            self.stdout.write("TentangFuki: deskripsi contoh diisi")

        # Mosaik "Apa Itu Fuki" sengaja TIDAK diisi: beranda hanya menampilkan
        # ubin yang berkas gambarnya ada, jadi baris contoh tanpa foto tidak akan
        # kelihatan sama sekali dan hanya menyesatkan.
        self.stdout.write(self.style.WARNING(
            "TentangFukiGambar: dilewati — unggah foto asli lewat /admin "
            "agar mosaik 'Apa Itu Fuki' tampil."
        ))

        for i in range(1, 4):
            self.buat(Activity, f"{PREFIX} Dokumentasi Kegiatan {i}", {
                "deskripsi": LOREM,
                "urutan": i,
            })

        for i in range(1, 4):
            self.buat(Podcast, f"{PREFIX} FUKInian - Eps {i}", {
                "deskripsi": LOREM,
                "link": "https://open.spotify.com/",
                "urutan": i,
            })

        for i in range(1, 5):
            self.buat(CompanyProfile, f"{PREFIX} Company Profile {i}", {
                "deskripsi": "Lorem ipsum dolor sit amet.",
                "link": "https://www.youtube.com/@fukifasilkomui",
                "urutan": i,
            })

        # Satu kegiatan per kategori, semuanya bertanggal mendatang, supaya
        # keempat tab filter di beranda punya isi untuk dibuktikan.
        hari_ini = datetime.date.today()
        for i, (kategori, label) in enumerate(Kegiatan.KATEGORI_CHOICES):
            self.buat(Kegiatan, f"{PREFIX} {label}", {
                "deskripsi": LOREM,
                "kategori": kategori,
                "tanggal": hari_ini + datetime.timedelta(days=7 + i),
                "start_time": datetime.time(7, 0),
                "end_time": datetime.time(15, 0),
                "lokasi": "Auditorium Fasilkom UI",
                "guest_star": "Ustadz Fulan",
                "contact": "0812-0000-0000",
            })

        self.stdout.write(self.style.SUCCESS(
            f"Selesai. Jalankan 'manage.py seed_beranda --clear' untuk menghapusnya lagi."
        ))

    def buat(self, model, judul, defaults):
        _, dibuat = model.objects.get_or_create(judul=judul, defaults=defaults)
        if dibuat:
            self.stdout.write(f"{model.__name__}: {judul}")
