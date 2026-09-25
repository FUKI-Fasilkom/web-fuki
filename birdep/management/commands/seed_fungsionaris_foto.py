"""Isi ``foto_path`` fungsionaris & pengurus inti dari CSV nama -> path aset.

Contoh pemakaian:

    # cek dulu tanpa menulis apa pun
    python manage.py seed_fungsionaris_foto --dry-run

    # jalankan sungguhan (CSV bawaan: birdep/seed/fungsionaris_foto.csv)
    python manage.py seed_fungsionaris_foto

CSV berisi dua kolom, ``nama`` (Nama Lengkap) dan ``foto_path`` (path aset di
static/, mis. ``images/fungsionaris/lanang.jpg``). Barisnya dicocokkan ke
``birdep.Fungsionaris`` dan ``birdep.PengurusInti`` lewat nama, tanpa peduli
huruf besar-kecil dan spasi berlebih. Cocok dengan barisnya sendiri, jadi aman
dijalankan di prod yang datanya sudah terisi: hanya ``foto_path`` yang disentuh,
dan menjalankannya ulang tidak mengubah apa pun.
"""

import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from birdep.models import Fungsionaris, PengurusInti

CSV_DEFAULT = Path(__file__).resolve().parents[2] / "seed" / "fungsionaris_foto.csv"
KOLOM = ("nama", "foto_path")


def _kunci(nama):
    return " ".join((nama or "").split()).casefold()


def baca_csv(path):
    """Kembalikan ``[(nomor_baris, nama, foto_path)]``; gagal keras bila kolom kurang."""
    with open(path, encoding="utf-8-sig", newline="") as berkas:
        reader = csv.DictReader(berkas)
        hilang = [k for k in KOLOM if k not in (reader.fieldnames or [])]
        if hilang:
            raise CommandError(f"{Path(path).name}: kolom {', '.join(hilang)} tidak ada.")
        return [
            (reader.line_num, " ".join(row["nama"].split()), row["foto_path"].strip())
            for row in reader
            if (row["nama"] or "").strip()
        ]


def _ada_di_static(foto_path):
    """True bila aset ada di salah satu folder static proyek (STATICFILES_DIRS/STATIC_ROOT)."""
    akar = [Path(d) for d in settings.STATICFILES_DIRS] + [Path(settings.STATIC_ROOT)]
    return any((a / foto_path).is_file() for a in akar)


class Command(BaseCommand):
    help = "Isi foto_path Fungsionaris & PengurusInti dari CSV (nama -> path aset)."

    def add_arguments(self, parser):
        parser.add_argument(
            "berkas", nargs="?", default=str(CSV_DEFAULT),
            help="Path CSV (default: birdep/seed/fungsionaris_foto.csv)",
        )
        parser.add_argument("--dry-run", action="store_true",
                            help="Hanya melaporkan, tidak menulis ke database.")

    @transaction.atomic
    def handle(self, *args, **opts):
        berkas = Path(opts["berkas"])
        if not berkas.exists():
            raise CommandError(f"Berkas tidak ditemukan: {berkas}")

        peta = {}
        for nomor, nama, foto_path in baca_csv(berkas):
            if not foto_path:
                raise CommandError(f"{berkas.name} baris {nomor}: foto_path kosong untuk '{nama}'.")
            if _kunci(nama) in peta:
                raise CommandError(f"{berkas.name} baris {nomor}: nama ganda '{nama}'.")
            peta[_kunci(nama)] = (nama, foto_path)

        cocok, diperbarui = set(), 0
        for model in (Fungsionaris, PengurusInti):
            for obyek in model.objects.all():
                entri = peta.get(_kunci(obyek.nama))
                if entri is None:
                    continue
                cocok.add(_kunci(obyek.nama))
                if obyek.foto_path != entri[1]:
                    diperbarui += 1
                    if not opts["dry_run"]:
                        # update() supaya updated_at/signal tidak ikut terpicu.
                        model.objects.filter(pk=obyek.pk).update(foto_path=entri[1])

        prefix = "[uji coba] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}{len(cocok)} dari {len(peta)} nama cocok, {diperbarui} foto_path diperbarui."
        ))
        for kunci, (nama, foto_path) in peta.items():
            if kunci not in cocok:
                self.stdout.write(self.style.WARNING(f"tidak ada di database: {nama}"))
            if not _ada_di_static(foto_path):
                self.stdout.write(self.style.WARNING(f"berkas tidak ada di static: {foto_path}"))
