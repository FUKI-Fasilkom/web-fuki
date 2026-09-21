"""Seed RSVP mentee yang sudah mengisi form lain (existing_rsvp.csv) ke website.

Hasilnya sama dengan RSVP lewat web: `EventRSVP` dengan token QR registrasi &
kupon dari default model, jadi halaman RSVP menampilkan QR yang ditandatangani
(`siwak.qr`) seperti biasa. QR tidak disimpan; ia dihitung dari token saat halaman
dibuka.

Orang dicocokkan lewat NPM ke `Profile` yang sudah ada (mentee dari CSV
pengelompokan maupun mentor). Mentor dari CSV mentor belum ber-NPM, jadi NPM yang
tidak ketemu dicari lagi lewat nama (harus sama persis dan tunggal); kalau ketemu,
NPM dari form dituliskan ke profil mentor itu supaya login SSO-nya bisa
mengklaim barisnya.

`EventRSVP.user` wajib terisi. Profil yang sudah punya akun login langsung dapat
`EventRSVP`; yang belum ditampung di `RSVPTertunda` (dengan token QR yang sudah
jadi) dan otomatis dipindahkan saat login SSO pertamanya (`sync_profile`). NPM yang
tetap tidak cocok dengan profil mana pun dilaporkan dan dilewati. Aman dijalankan
ulang: RSVP yang sudah ada tidak disentuh dan token tidak berubah.
"""

import csv
import datetime
import difflib
import re
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from siwak.models import EventRSVP, Profile, RSVPTertunda, SiwakEvent
from siwak.services.rsvp import buat_rsvp, klaim_rsvp_tertunda

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
            ("dibuat", "tertunda", "diperbarui", "sudah_ada", "lewat_nama",
             "tanpa_profil", "beda_nama"), 0
        )
        self.indeks_nama = defaultdict(list)
        for profil in Profile.objects.filter(auth_source=Profile.SOURCE_SSO):
            self.indeks_nama[kunci_nama(profil.nama_lengkap)].append(profil)
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
        dilewati = hasil["tanpa_profil"] + hasil["beda_nama"]
        self.stdout.write(
            f"RSVP dibuat (sudah punya akun): {hasil['dibuat']}. "
            f"Ditampung sampai login SSO: {hasil['tertunda']} "
            f"(diperbarui: {hasil['diperbarui']}). Sudah punya RSVP: {hasil['sudah_ada']}. "
            f"Dicocokkan lewat nama: {hasil['lewat_nama']}. "
            f"Dilewati: {dilewati} (tanpa Profile: {hasil['tanpa_profil']}, "
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

    def cari_lewat_nama(self, entri, catatan):
        """Profile SSO dengan nama yang sama persis (setelah dinormalisasi), atau None.

        Dipakai hanya kalau NPM dari form tidak cocok dengan profil mana pun. Harus
        tunggal: dua orang sekelas bisa saja bernama sama.
        """
        kandidat = self.indeks_nama.get(kunci_nama(entri["nama"]), [])
        if len(kandidat) == 1:
            return kandidat[0]
        if kandidat:
            catatan.append(
                f"{entri['label']}: NPM tidak ada di Profile, dan nama cocok dengan "
                f"{len(kandidat)} profil, dilewati."
            )
        else:
            catatan.append(f"{entri['label']}: tidak ada Profile dengan NPM atau nama ini, dilewati.")
        return None

    def seed_satu(self, entri, event, options, hasil, catatan):
        label = entri["label"]
        profil = Profile.objects.filter(npm=entri["npm"]).first()
        if profil is None:
            profil = self.cari_lewat_nama(entri, catatan)
            if profil is None:
                hasil["tanpa_profil"] += 1
                return
            peran = profil.get_role_display() or "tanpa peran"
            if profil.npm is None and profil.user_id is None:
                # Mentor dari CSV mentor: NPM inilah yang dipakai sync_profile untuk mengklaim barisnya.
                profil.npm = entri["npm"]
                profil.save(update_fields=["npm"])
                catatan.append(
                    f"{label}: dicocokkan lewat nama dengan {peran} \"{profil.nama_lengkap}\"; "
                    f"NPM {entri['npm']} dituliskan ke Profile."
                )
            elif profil.npm and profil.npm != entri["npm"]:
                catatan.append(
                    f"{label}: NPM di form beda dari Profile {peran} \"{profil.nama_lengkap}\" "
                    f"({profil.npm}), dicocokkan lewat nama; NPM Profile tidak diubah."
                )
            else:
                catatan.append(
                    f"{label}: dicocokkan lewat nama dengan {peran} \"{profil.nama_lengkap}\"."
                )
            hasil["lewat_nama"] += 1

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

        kehadiran, alasan_izin = kehadiran_dari_form(entri["jawaban"], entri["alasan"])
        if entri["jawaban"] == "ya" and alasan_bermakna(entri["alasan"]):
            catatan.append(
                f"{label}: hadir dengan keterangan \"{entri['alasan']}\"; keterangan tidak disimpan."
            )
        if entri["jawaban"] == "tidak" and len(entri["alasan"]) > BATAS_ALASAN:
            catatan.append(f"{label}: alasan dipotong jadi {BATAS_ALASAN} karakter.")

        if profil.user_id:
            # Sisa RSVP tertunda dari seed sebelumnya (akun ditautkan tanpa lewat sync_profile).
            klaim_rsvp_tertunda(profil)
            if EventRSVP.objects.filter(event=event, user_id=profil.user_id).exists():
                hasil["sudah_ada"] += 1
                return
            buat_rsvp(
                event=event, user=profil.user, kehadiran=kehadiran,
                alasan_izin=alasan_izin, dikirim_pada=entri["waktu"],
            )
            hasil["dibuat"] += 1
            return

        tertunda = RSVPTertunda.objects.filter(event=event, profile=profil).first()
        if tertunda is None:
            RSVPTertunda.objects.create(
                event=event, profile=profil, kehadiran=kehadiran,
                alasan_izin=alasan_izin, dikirim_pada=entri["waktu"],
            )
            hasil["tertunda"] += 1
            return
        # Seed ulang: token dibiarkan supaya QR tidak berubah, isi form disegarkan.
        baru = (kehadiran, alasan_izin, entri["waktu"])
        if baru == (tertunda.kehadiran, tertunda.alasan_izin, tertunda.dikirim_pada):
            hasil["sudah_ada"] += 1
            return
        tertunda.kehadiran, tertunda.alasan_izin, tertunda.dikirim_pada = baru
        tertunda.save(update_fields=["kehadiran", "alasan_izin", "dikirim_pada"])
        hasil["diperbarui"] += 1
