"""Seed RSVP mentee yang sudah mengisi form lain (existing_rsvp.csv) ke website.

Hasilnya sama dengan RSVP lewat web: `EventRSVP` dengan token QR registrasi &
kupon dari default model, jadi halaman RSVP menampilkan QR yang ditandatangani
(`siwak.qr`) seperti biasa. QR tidak disimpan; ia dihitung dari token saat halaman
dibuka.

Mentee dicocokkan lewat NPM ke `Profile` yang sudah ada. `EventRSVP.user` wajib
terisi, jadi hanya profil yang sudah punya akun login (pernah login SSO) yang bisa
di-seed; NPM tanpa Profile, atau Profile yang belum pernah login, dilaporkan dan
dilewati. Aman dijalankan ulang setelah lebih banyak mentee login: yang sudah
punya RSVP tidak disentuh.
"""

import csv
import datetime
import difflib
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from siwak.models import EventRSVP, Profile, SiwakEvent

RSVP_CSV_DEFAULT = "existing_rsvp.csv"
KOLOM_WAJIB = ("Timestamp", "Nama Lengkap", "NPM", "Apakah kamu bisa hadir?")
PREFIKS_KOLOM_ALASAN = "Apa alasan"
FORMAT_TIMESTAMP = "%d/%m/%Y %H:%M:%S"
BATAS_ALASAN = EventRSVP._meta.get_field("alasan_izin").max_length


class _Rollback(Exception):
    """Dipakai --dry-run untuk membatalkan transaksi setelah laporan tercetak."""


def _rapikan(teks):
    return " ".join((teks or "").split())


def kunci_nama(nama):
    """Nama tanpa huruf besar/kecil, spasi, dan tanda baca ("M.Januar" == "M. Januar")."""
    return re.sub(r"[\W_]+", "", (nama or "").casefold())


def bandingkan_nama(nama_profil, nama_csv):
    """``"sama"`` | ``"mirip"`` | ``"beda"``.

    ``mirip`` mencakup nama yang terpotong di form ("Farras A" vs "Farras Arizanov")
    dan salah ketik satu-dua huruf; ``beda`` berarti kemungkinan NPM tertukar.
    """
    a, b = kunci_nama(nama_profil), kunci_nama(nama_csv)
    if a == b:
        return "sama"
    if a and b and (a.startswith(b) or b.startswith(a)):
        return "mirip"
    if difflib.SequenceMatcher(None, a, b).ratio() >= 0.85:
        return "mirip"
    return "beda"


def alasan_bermakna(alasan):
    """False untuk isian penanda "tidak ada" seperti "-", "---", "_", '"-"'."""
    return bool(re.search(r"[^\W_]", alasan or ""))


def kehadiran_dari_form(jawaban, alasan):
    """Petakan jawaban form ke ``(kehadiran, alasan_izin)`` milik EventRSVP.

    "Ya" -> hadir. "Tidak" + alasan -> izin (form web mewajibkan alasan untuk izin);
    "Tidak" tanpa alasan -> tidak_hadir. Alasan hanya disimpan untuk izin, seperti
    di form web.
    """
    if jawaban == "ya":
        return "hadir", ""
    if jawaban == "tidak":
        if alasan_bermakna(alasan):
            return "izin", alasan[:BATAS_ALASAN]
        return "tidak_hadir", ""
    raise ValueError(jawaban)


def baca_rsvp(path, catatan):
    """Baca CSV form menjadi satu dict per NPM (submit terbaru menang) plus jumlah baris."""
    try:
        berkas = open(path, encoding="utf-8-sig", newline="")
    except OSError as e:
        raise CommandError(f"CSV tidak bisa dibaca: {path} ({e})")
    with berkas:
        reader = csv.DictReader(berkas)
        fields = reader.fieldnames or []
        hilang = [k for k in KOLOM_WAJIB if k not in fields]
        kol_alasan = next((f for f in fields if f.startswith(PREFIKS_KOLOM_ALASAN)), None)
        if kol_alasan is None:
            hilang.append(f"{PREFIKS_KOLOM_ALASAN}...")
        if hilang:
            raise CommandError(f"{Path(path).name}: kolom {', '.join(hilang)} tidak ada.")

        per_npm = {}
        jumlah = 0
        for row in reader:
            jumlah += 1
            nomor = reader.line_num
            npm = _rapikan(row["NPM"])
            nama = _rapikan(row["Nama Lengkap"])
            label = f"baris {nomor} ({nama or '?'} · {npm or '?'})"
            if not npm.isdigit():
                catatan.append(f"{label}: NPM tidak valid, dilewati.")
                continue
            jawaban = _rapikan(row["Apakah kamu bisa hadir?"]).casefold()
            if jawaban not in ("ya", "tidak"):
                catatan.append(f"{label}: jawaban \"{jawaban}\" tidak dikenali, dilewati.")
                continue
            try:
                waktu = timezone.make_aware(
                    datetime.datetime.strptime(_rapikan(row["Timestamp"]), FORMAT_TIMESTAMP)
                )
            except ValueError:
                catatan.append(f"{label}: timestamp tidak valid, dilewati.")
                continue

            entri = {
                "nomor": nomor, "npm": npm, "nama": nama, "jawaban": jawaban,
                "alasan": _rapikan(row[kol_alasan]), "waktu": waktu, "label": label,
            }
            # Submit ulang = koreksi: yang terbaru (waktu, lalu urutan baris) menang.
            lama = per_npm.get(npm)
            if lama:
                baru, usang = (entri, lama) if (waktu, nomor) >= (lama["waktu"], lama["nomor"]) \
                    else (lama, entri)
                if (baru["jawaban"], baru["alasan"]) != (usang["jawaban"], usang["alasan"]):
                    catatan.append(
                        f"{baru['label']}: mengisi ulang dengan jawaban berbeda dari "
                        f"baris {usang['nomor']}, jawaban terbaru dipakai."
                    )
                entri = baru
            per_npm[npm] = entri
    return per_npm, jumlah


class Command(BaseCommand):
    help = (
        "Isi RSVP mentee yang sudah mengisi form lain (existing_rsvp.csv) supaya "
        "halaman RSVP di website menampilkan QR mereka seperti hasil RSVP lewat web."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv", metavar="PATH",
            help=f"CSV respons form (bawaan: {RSVP_CSV_DEFAULT} di root proyek).",
        )
        parser.add_argument(
            "--event", type=int, metavar="ID",
            help="ID SiwakEvent tujuan. Boleh dihilangkan kalau hanya ada satu event.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Jalankan semuanya dan cetak laporan, lalu batalkan (tidak ada yang tersimpan).",
        )
        parser.add_argument(
            "--terima-beda-nama", action="store_true",
            help="Tetap seed walau nama di CSV sangat berbeda dari nama Profile (bawaan: dilewati).",
        )

    def handle(self, *args, **options):
        catatan = []
        path = Path(options["csv"]) if options["csv"] else Path(settings.BASE_DIR) / RSVP_CSV_DEFAULT
        if not path.is_file():
            raise CommandError(f"CSV tidak ditemukan: {path}")
        event = self.pilih_event(options["event"])
        per_npm, jumlah_baris = baca_rsvp(path, catatan)
        if not per_npm:
            raise CommandError("Tidak ada baris valid di CSV, tidak ada yang diisi.")

        hasil = dict.fromkeys(
            ("dibuat", "sudah_ada", "tanpa_profil", "belum_login", "beda_nama"), 0
        )
        try:
            with transaction.atomic():
                for entri in per_npm.values():
                    self.seed_satu(entri, event, options, hasil, catatan)
                if options["dry_run"]:
                    raise _Rollback
        except _Rollback:
            pass

        self.stdout.write(
            f"Event: {event}. CSV: {jumlah_baris} baris, {len(per_npm)} NPM unik "
            f"({jumlah_baris - len(per_npm)} submit ulang/tak valid)."
        )
        dilewati = hasil["tanpa_profil"] + hasil["belum_login"] + hasil["beda_nama"]
        self.stdout.write(
            f"RSVP dibuat: {hasil['dibuat']}. Sudah punya RSVP: {hasil['sudah_ada']}. "
            f"Dilewati: {dilewati} (tanpa Profile: {hasil['tanpa_profil']}, "
            f"Profile belum punya akun login: {hasil['belum_login']}, "
            f"nama beda: {hasil['beda_nama']})."
        )
        if catatan:
            self.stdout.write(self.style.WARNING(f"{len(catatan)} catatan untuk dicek:"))
            for baris in catatan:
                self.stdout.write(self.style.WARNING(f"  - {baris}"))
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("DRY RUN: tidak ada yang disimpan."))
        else:
            self.stdout.write(self.style.SUCCESS("RSVP existing berhasil di-seed."))

    def pilih_event(self, event_id):
        if event_id is not None:
            try:
                return SiwakEvent.objects.get(pk=event_id)
            except SiwakEvent.DoesNotExist:
                raise CommandError(f"SiwakEvent id={event_id} tidak ada.")
        events = list(SiwakEvent.objects.all())
        if len(events) == 1:
            return events[0]
        daftar = ", ".join(f"{e.pk}={e.judul}" for e in events) or "(kosong)"
        raise CommandError(f"Ada {len(events)} event, pilih dengan --event ID. Tersedia: {daftar}")

    def seed_satu(self, entri, event, options, hasil, catatan):
        label = entri["label"]
        profil = Profile.objects.filter(npm=entri["npm"]).first()
        if profil is None:
            catatan.append(f"{label}: tidak ada Profile dengan NPM ini, dilewati.")
            hasil["tanpa_profil"] += 1
            return

        cocok = bandingkan_nama(profil.nama_lengkap, entri["nama"])
        if cocok == "beda":
            pesan = (
                f"{label}: nama di Profile \"{profil.nama_lengkap}\" sangat berbeda dari "
                f"CSV \"{entri['nama']}\""
            )
            if not options["terima_beda_nama"]:
                catatan.append(f"{pesan}, dilewati (pakai --terima-beda-nama).")
                hasil["beda_nama"] += 1
                return
            catatan.append(f"{pesan}, tetap di-seed.")
        elif cocok == "mirip":
            catatan.append(
                f"{label}: nama di Profile \"{profil.nama_lengkap}\" sedikit beda dari "
                f"CSV \"{entri['nama']}\", tetap di-seed."
            )

        if profil.user_id is None:
            catatan.append(
                f"{label}: Profile belum punya akun login (belum pernah login SSO), dilewati; "
                "jalankan ulang setelah orangnya login."
            )
            hasil["belum_login"] += 1
            return

        kehadiran, alasan_izin = kehadiran_dari_form(entri["jawaban"], entri["alasan"])
        if entri["jawaban"] == "ya" and alasan_bermakna(entri["alasan"]):
            catatan.append(
                f"{label}: hadir dengan keterangan \"{entri['alasan']}\"; keterangan tidak disimpan."
            )
        if entri["jawaban"] == "tidak" and len(entri["alasan"]) > BATAS_ALASAN:
            catatan.append(f"{label}: alasan dipotong jadi {BATAS_ALASAN} karakter.")

        if EventRSVP.objects.filter(event=event, user_id=profil.user_id).exists():
            hasil["sudah_ada"] += 1
            return

        # Sama dengan rsvp_event: token QR registrasi & kupon, status_kehadiran
        # (belum_hadir) dan status_kupon (unused) semuanya dari default model.
        rsvp = EventRSVP.objects.create(
            event=event, user=profil.user, kehadiran=kehadiran, alasan_izin=alasan_izin
        )
        # created_at auto_now_add: hanya bisa ditimpa lewat update().
        EventRSVP.objects.filter(pk=rsvp.pk).update(created_at=entri["waktu"])
        hasil["dibuat"] += 1
