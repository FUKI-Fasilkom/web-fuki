import csv
import datetime
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from siwak.models import (
    FAQMentoring,
    KelompokMentoring,
    KetuaSiwak,
    Profile,
    MentoringBenefit,
    MentoringTujuan,
    SistemMentoring,
    SiwakEvent,
    SiwakInfo,
    TimelineEvent,
    Tugas,
)

# Data pengelompokan, satu berkas per gender, dicari di root proyek.
PENGELOMPOKAN_CSV_DEFAULT = (
    "SIWAK_2026_Pengelompokan_Mentoring_Group_Ikhwan.csv",
    "SIWAK_2026_Pengelompokan_Mentoring_Group_Akhwat.csv",
)
PENGELOMPOKAN_KOLOM = ("Kelompok", "Nama", "NPM", "Group Whatsapp")
MENTOR_CSV_DEFAULT = (
    "Kelompok_Mentor_Ikhwan.csv",
    "Kelompok_Mentor_Akhwat.csv",
)
MENTOR_KOLOM = ("Kelompok", "Mentor")


def _baca_csv(path, kolom):
    """Hasilkan ``(nomor_baris, row)``; gagal keras kalau kolom yang dibutuhkan tidak ada."""
    with open(path, encoding="utf-8-sig", newline="") as berkas:
        reader = csv.DictReader(berkas)
        hilang = [k for k in kolom if k not in (reader.fieldnames or [])]
        if hilang:
            raise CommandError(f"{path.name}: kolom {', '.join(hilang)} tidak ada.")
        for row in reader:
            yield reader.line_num, row


def baca_pengelompokan(path):
    """Baca satu CSV pengelompokan mentee menjadi ``(baris, sisa)``.

    ``baris`` hanya berisi baris yang punya Nama. Baris tanpa Nama sama sekali
    (mis. daftar link yang tertempel di kaki berkas) tidak bisa jadi orang mana
    pun, jadi cuma dihitung di ``sisa``.
    """
    baris, sisa = [], 0
    for nomor, row in _baca_csv(path, PENGELOMPOKAN_KOLOM):
        nama = " ".join((row["Nama"] or "").split())
        if not nama:
            sisa += 1
            continue
        baris.append({
            "sumber": path.name,
            "nomor": nomor,
            "kelompok": (row["Kelompok"] or "").strip(),
            "nama": nama,
            "npm": (row["NPM"] or "").strip(),
            "link": (row["Group Whatsapp"] or "").strip(),
        })
    return baris, sisa


def baca_mentor(path):
    """Baca satu CSV mentor menjadi ``(baris, sisa)``, satu baris per mentor.

    Satu sel boleh memuat dua mentor yang dipisah "&" (kelompok yang dipegang
    berdua); masing-masing jadi baris sendiri.
    """
    baris, sisa = [], 0
    for nomor, row in _baca_csv(path, MENTOR_KOLOM):
        nama_nama = [" ".join(n.split()) for n in (row["Mentor"] or "").split("&")]
        nama_nama = [n for n in nama_nama if n]
        if not nama_nama:
            sisa += 1
            continue
        for nama in nama_nama:
            baris.append({
                "sumber": path.name,
                "nomor": nomor,
                "kelompok": (row["Kelompok"] or "").strip(),
                "nama": nama,
            })
    return baris, sisa


class Command(BaseCommand):
    help = (
        "Isi data contoh untuk section SIWAK supaya halaman tidak kosong saat QA/demo, "
        "plus kelompok (dengan link grup WhatsApp), mentee, dan mentor dari CSV pengelompokan."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            action="append",
            metavar="PATH",
            help=(
                "CSV pengelompokan (kolom Kelompok, Nama, NPM, Group Whatsapp); boleh "
                "diulang. Bawaan: dua berkas SIWAK_2026_Pengelompokan_* di root proyek."
            ),
        )
        parser.add_argument(
            "--mentor-csv",
            action="append",
            metavar="PATH",
            help=(
                "CSV mentor per kelompok (kolom Kelompok, Mentor); boleh diulang. "
                "Bawaan: dua berkas Kelompok_Mentor_* di root proyek."
            ),
        )
        parser.add_argument(
            "--csv-only",
            action="store_true",
            help=(
                "Hanya isi kelompok, mentee, dan mentor dari CSV; lewati seluruh data "
                "contoh (info SIWAK, event, tugas, dst.). Ini yang aman dipakai di "
                "server: data contoh memakai update_or_create dan menimpa konten asli."
            ),
        )

    def handle(self, *args, **options):
        # Dibaca paling awal supaya berkas rusak menggagalkan perintah sebelum
        # ada data yang tertulis.
        catatan = []
        pengelompokan = self.muat_pengelompokan(options["csv"], catatan)
        mentor = self.muat_mentor(options["mentor_csv"], catatan)

        if options["csv_only"]:
            if not pengelompokan and not mentor:
                raise CommandError(
                    "Tidak ada CSV yang terbaca, tidak ada yang diisi. "
                    "Salin berkas ke root proyek atau tunjuk lewat --csv / --mentor-csv."
                )
            with transaction.atomic():
                self.seed_pengelompokan(pengelompokan, catatan)
                self.seed_mentor(mentor, catatan)
            self.tulis_catatan(catatan)
            self.stdout.write(self.style.SUCCESS("Data pengelompokan SIWAK berhasil diisi."))
            return

        today = timezone.localdate()

        info = SiwakInfo.get_solo()
        info.hero_judul = "SIWAK-NG"
        info.apa_itu_deskripsi = (
            "SIWAK-NG adalah rangkaian kegiatan mentoring dan pengenalan nilai-nilai keislaman "
            "bagi mahasiswa baru muslim Fasilkom UI, diselenggarakan oleh FUKI."
        )
        info.mentoring_deskripsi = (
            "Mentoring adalah sesi pemaparan materi keagamaan dengan membuat kelompok kecil "
            "bersama mentor-mentor berpengalaman."
        )
        info.kontak_cp = "https://wa.me/6281234567890"
        info.save()

        SiwakEvent.objects.update_or_create(
            judul="Pre-Event SIWAK",
            defaults=dict(
                deskripsi="Sesi pembukaan dan pengenalan kelompok mentoring.",
                tanggal=today + datetime.timedelta(days=10),
                lokasi="Auditorium Fasilkom UI",
                urutan=1,
            ),
        )
        SiwakEvent.objects.update_or_create(
            judul="Main Event SIWAK",
            defaults=dict(
                deskripsi="Puncak acara SIWAK-NG dengan tausiyah dan penutupan mentoring.",
                tanggal=today + datetime.timedelta(days=30),
                lokasi="Balairung UI",
                urutan=2,
            ),
        )

        for i, (judul, desc) in enumerate([
            ("Tujuan pertama", "Membangun ukhuwah islamiyah antar mahasiswa baru Fasilkom UI."),
            ("Tujuan kedua", "Memberikan bekal wawasan keislaman dasar bagi mahasiswa baru."),
            ("Tujuan ketiga", "Mengenalkan lingkungan kampus dan komunitas muslim Fasilkom."),
        ]):
            MentoringTujuan.objects.update_or_create(judul=judul, defaults={"deskripsi": desc, "urutan": i})

        for i, (judul, desc) in enumerate([
            ("Benefit 1", "Mendapat teman baru lintas jurusan dan angkatan."),
            ("Benefit 2", "Bimbingan langsung dari mentor berpengalaman."),
            ("Benefit 3", "Sertifikat keikutsertaan mentoring."),
            ("Benefit 4", "Akses ke jaringan komunitas FUKI Fasilkom UI."),
        ]):
            MentoringBenefit.objects.update_or_create(judul=judul, defaults={"deskripsi": desc, "urutan": i})

        for i, desc in enumerate([
            "Mentoring dilakukan dalam kelompok kecil berisi 10-15 orang.",
            "Setiap kelompok didampingi 2 mentor sepanjang masa mentoring.",
            "Pertemuan dilakukan rutin sesuai jadwal yang disepakati kelompok.",
        ]):
            SistemMentoring.objects.update_or_create(deskripsi=desc, defaults={"urutan": i})

        for i, (nama, tahun) in enumerate([("Fulan bin Fulan", "2025"), ("Fulanah binti Fulan", "2024"), ("Fulan Al-Fasilkomi", "2023")]):
            KetuaSiwak.objects.update_or_create(nama=nama, tahun=tahun, defaults={"urutan": i})

        TimelineEvent.objects.update_or_create(
            judul="Pembagian Kelompok Mentoring",
            defaults=dict(
                kategori="pembagian_kelompok",
                deskripsi="Pengumuman kelompok dan mentor lewat halaman Cari Kelompok.",
                tanggal_mulai=today - datetime.timedelta(days=5),
            ),
        )
        TimelineEvent.objects.update_or_create(
            judul="Mentoring Berjalan",
            defaults=dict(
                kategori="mentoring",
                deskripsi="Sesi mentoring rutin dan pengumpulan tugas.",
                tanggal_mulai=today - datetime.timedelta(days=2),
                tanggal_selesai=today + datetime.timedelta(days=8),
            ),
        )
        TimelineEvent.objects.update_or_create(
            judul="Pre-Event SIWAK",
            defaults=dict(
                kategori="pre_event",
                tanggal_mulai=today + datetime.timedelta(days=10),
            ),
        )
        TimelineEvent.objects.update_or_create(
            judul="Main Event SIWAK",
            defaults=dict(
                kategori="main_event",
                tanggal_mulai=today + datetime.timedelta(days=30),
            ),
        )

        FAQMentoring.objects.update_or_create(
            pertanyaan="Apakah mentoring wajib diikuti?",
            defaults={"jawaban": "Ya, mentoring merupakan bagian dari rangkaian SIWAK-NG untuk maba muslim.", "urutan": 0},
        )
        FAQMentoring.objects.update_or_create(
            pertanyaan="Bagaimana jika belum mendapat kelompok?",
            defaults={"jawaban": "Gunakan menu 'Cari Kelompok' atau hubungi CP SIWAK yang tertera.", "urutan": 1},
        )

        kelompok1, _ = KelompokMentoring.objects.get_or_create(
            nama_kelompok="Kelompok 1",
            defaults={"link_grup": "https://chat.whatsapp.com/contoh-link-kelompok-1"},
        )

        # Mentor dan mentee sama-sama Profile; bedanya hanya `role`.
        # Mentor diberi NPM supaya baris ini tersambung ke akunnya begitu login
        # SSO (NPM contoh ini fiktif — ganti dengan NPM asli saat QA dengan akun sungguhan).
        for npm, nama, jurusan in (
            ("2206000001", "Kak Ahmad", "IK"),
            ("2206000002", "Kak Fatimah", "SI"),
        ):
            Profile.objects.update_or_create(
                npm=npm,
                defaults={
                    "nama_lengkap": nama,
                    "jurusan": jurusan,
                    "angkatan": "2022",
                    "role": Profile.ROLE_MENTOR,
                    "kelompok": kelompok1,
                },
            )

        Profile.objects.update_or_create(
            npm="2506000001",
            defaults={
                "nama_lengkap": "Marwa Muhlashon",
                "jurusan": "SI",
                "angkatan": "2025",
                "role": Profile.ROLE_MENTEE,
                "kelompok": kelompok1,
            },
        )

        self.seed_pengelompokan(pengelompokan, catatan)
        self.seed_mentor(mentor, catatan)

        Tugas.objects.update_or_create(
            judul_tugas="Tugas Perkenalan",
            defaults=dict(
                deskripsi="Perkenalkan dirimu secara singkat kepada mentor dan teman sekelompok.",
                deadline=timezone.now() + datetime.timedelta(days=3),
            ),
        )
        Tugas.objects.update_or_create(
            judul_tugas="Tugas Refleksi Diri",
            defaults=dict(
                deskripsi=(
                    "Buat tulisan singkat (maks. 300 kata) berisi perkenalan diri, alasan memilih "
                    "jurusan/kampus ini, serta harapan yang ingin dicapai selama masa ospek.\n"
                    "Sertakan juga satu hal unik tentang dirimu yang ingin diketahui teman-teman "
                    "mentor dan sesama peserta. Tugas dikumpulkan dalam format PDF atau DOCX."
                ),
                deadline=timezone.now() + datetime.timedelta(days=1),
            ),
        )
        Tugas.objects.update_or_create(
            judul_tugas="Tugas Kelompok 1",
            defaults=dict(
                deskripsi="Diskusikan bersama kelompok dan kumpulkan hasil diskusi kalian.",
                deadline=timezone.now() - datetime.timedelta(days=2),
            ),
        )

        self.tulis_catatan(catatan)
        self.stdout.write(self.style.SUCCESS("Data contoh SIWAK berhasil diisi."))

    def cari_csv(self, csv_paths, default, catatan):
        """Path CSV yang dipakai: yang diminta eksplisit (wajib ada) atau bawaan (boleh tidak ada)."""
        if csv_paths:
            paths = [Path(p) for p in csv_paths]
            for path in paths:
                if not path.is_file():
                    raise CommandError(f"CSV tidak ditemukan: {path}")
            return paths

        # Berkas bawaan tidak ikut di-commit (berisi data pribadi), jadi
        # ketiadaannya wajar: seed lain tetap jalan.
        paths = []
        for nama in default:
            path = Path(settings.BASE_DIR) / nama
            if path.is_file():
                paths.append(path)
            else:
                catatan.append(f"{nama} tidak ditemukan, dilewati.")
        return paths

    def muat_pengelompokan(self, csv_paths, catatan):
        baris = []
        for path in self.cari_csv(csv_paths, PENGELOMPOKAN_CSV_DEFAULT, catatan):
            rows, sisa = baca_pengelompokan(path)
            baris.extend(rows)
            if sisa:
                catatan.append(
                    f"{path.name}: {sisa} baris tanpa nama diabaikan "
                    "(sisa tempelan di kaki berkas?)."
                )
        return baris

    def muat_mentor(self, csv_paths, catatan):
        baris = []
        for path in self.cari_csv(csv_paths, MENTOR_CSV_DEFAULT, catatan):
            rows, sisa = baca_mentor(path)
            baris.extend(rows)
            if sisa:
                catatan.append(f"{path.name}: {sisa} baris tanpa mentor diabaikan.")
        return baris

    @transaction.atomic
    def seed_pengelompokan(self, baris, catatan):
        """Buat tiap Kelompok beserta link grup WhatsApp dan kapasitasnya, baru lalu isi mentee-nya.

        Kunci mentee adalah NPM: barisnya belum ber-`user`, dan `sync_profile`
        mengklaimnya saat orangnya login SSO pertama kali (sekaligus mengisi
        jurusan, yang tidak ada di CSV). Karena itu baris tanpa NPM tidak bisa
        di-seed: tidak ada yang mengklaimnya dan tiap seed ulang akan
        menggandakannya.
        """
        if not baris:
            return

        # 1) Kelompok + link WhatsApp. Link diambil dari baris pertama yang punya.
        link_kelompok = {}
        for b in baris:
            if not b["kelompok"]:
                continue
            link = link_kelompok.setdefault(b["kelompok"], "")
            if not b["link"]:
                continue
            if not b["link"].startswith(("http://", "https://")):
                catatan.append(
                    f"{b['sumber']}:{b['nomor']}: link \"{b['link']}\" bukan URL, diabaikan."
                )
            elif not link:
                link_kelompok[b["kelompok"]] = b["link"]
            elif link != b["link"]:
                catatan.append(
                    f"Kelompok {b['kelompok']} punya lebih dari satu link; "
                    f"dipakai yang pertama ({b['sumber']}:{b['nomor']} diabaikan)."
                )

        pemakai_link = defaultdict(list)
        for nama, link in link_kelompok.items():
            if link:
                pemakai_link[link.split("?")[0]].append(nama)
        for link, nama_nama in pemakai_link.items():
            if len(nama_nama) > 1:
                catatan.append(
                    f"Link {link} dipakai bersama oleh {len(nama_nama)} kelompok "
                    f"({', '.join(nama_nama)}); pastikan ini memang disengaja."
                )

        # Kapasitas = jumlah mentee yang dicantumkan CSV untuk kelompok itu. Semua
        # baris dihitung, termasuk yang tak bisa di-seed (tanpa NPM, atau NPM-nya
        # ditempatkan di kelompok lain): kapasitas menyatakan ukuran kelompok di
        # atas kertas, jadi "terisi/kapasitas" di panel memperlihatkan siapa yang
        # masih perlu dilengkapi. NPM yang berulang di kelompok yang sama dihitung
        # sekali.
        anggota_csv = defaultdict(set)
        for b in baris:
            if b["kelompok"]:
                anggota_csv[b["kelompok"]].add(b["npm"] or (b["sumber"], b["nomor"]))

        kelompok_by_nama = {}
        dibuat = diperbarui = 0
        for nama, link in link_kelompok.items():
            kapasitas = len(anggota_csv[nama])
            kelompok = KelompokMentoring.objects.filter(nama_kelompok=nama).order_by("pk").first()
            if kelompok is None:
                kelompok = KelompokMentoring.objects.create(
                    nama_kelompok=nama, link_grup=link, kapasitas=kapasitas
                )
                dibuat += 1
            elif (kelompok.link_grup, kelompok.kapasitas) != (link, kapasitas):
                kelompok.link_grup = link
                kelompok.kapasitas = kapasitas
                kelompok.save(update_fields=["link_grup", "kapasitas"])
                diperbarui += 1
            kelompok_by_nama[nama] = kelompok

        # 2) Mentee. Satu NPM cuma boleh punya satu kelompok (Profile.kelompok satu
        #    FK): kemunculan pertama menang, sisanya dilaporkan.
        ditempatkan = {}
        mentee_dibuat = mentee_diperbarui = 0
        for b in baris:
            label = f"{b['sumber']}:{b['nomor']} ({b['kelompok'] or '?'} · {b['nama']})"
            if not b["kelompok"]:
                catatan.append(f"{label}: tanpa kelompok, dilewati.")
                continue
            if not b["npm"]:
                catatan.append(f"{label}: tanpa NPM, dilewati.")
                continue
            if not b["npm"].isdigit():
                catatan.append(f"{label}: NPM \"{b['npm']}\" tidak valid, dilewati.")
                continue
            if b["npm"] in ditempatkan:
                if ditempatkan[b["npm"]] != b["kelompok"]:
                    catatan.append(
                        f"{label}: NPM {b['npm']} sudah masuk {ditempatkan[b['npm']]}; "
                        "penempatan pertama dipakai."
                    )
                continue
            ditempatkan[b["npm"]] = b["kelompok"]
            kelompok = kelompok_by_nama[b["kelompok"]]

            profil = Profile.objects.filter(npm=b["npm"]).first()
            if profil is None:
                Profile.objects.create(
                    npm=b["npm"],
                    nama_lengkap=b["nama"],
                    # jurusan sengaja kosong: CSV tidak memilikinya, sync SSO yang mengisi.
                    angkatan=f"20{b['npm'][:2]}",
                    role=Profile.ROLE_MENTEE,
                    kelompok=kelompok,
                )
                mentee_dibuat += 1
            elif profil.role == Profile.ROLE_MENTOR or profil.is_akun_lokal:
                catatan.append(f"{label}: NPM {b['npm']} sudah terdaftar sebagai mentor, dilewati.")
            else:
                # Nama tidak disentuh: kalau orangnya sudah login, namanya dari SSO.
                profil.role = Profile.ROLE_MENTEE
                profil.kelompok = kelompok
                profil.save(update_fields=["role", "kelompok"])
                mentee_diperbarui += 1

        self.stdout.write(
            f"Kelompok CSV: {dibuat} dibuat, {diperbarui} diperbarui (link/kapasitas), "
            f"{len(kelompok_by_nama)} total. "
            f"Mentee CSV: {mentee_dibuat} dibuat, {mentee_diperbarui} diperbarui."
        )

    @transaction.atomic
    def seed_mentor(self, baris, catatan):
        """Pasang mentor ke kelompoknya; berjalan setelah `seed_pengelompokan`.

        CSV mentor hanya berisi nama, tanpa NPM. Barisnya jadi Profile mentor
        tanpa NPM dan tanpa `user`, sama seperti mentor yang disiapkan staf di
        panel: tampil sebagai pemegang kelompok (mis. di hasil Cari Kelompok),
        tapi belum bisa login sampai staf mengisi NPM-nya di daftar Mentor panel
        — NPM itulah yang dipakai `sync_profile` untuk mengklaim barisnya.

        Tanpa NPM sebagai kunci, mentor dicocokkan lewat nama di antara mentor
        yang sudah ada, jadi seed ulang dan mentor buatan staf tidak digandakan.
        """
        if not baris:
            return

        dibuat = ditempatkan = 0
        memegang = {}
        kelompok_baru = set()
        for b in baris:
            label = f"{b['sumber']}:{b['nomor']} ({b['kelompok'] or '?'} · {b['nama']})"
            if not b["kelompok"]:
                catatan.append(f"{label}: tanpa kelompok, dilewati.")
                continue
            kunci = b["nama"].casefold()
            if kunci in memegang:
                if memegang[kunci] != b["kelompok"]:
                    catatan.append(
                        f"{label}: sudah memegang {memegang[kunci]}; "
                        "penempatan pertama dipakai."
                    )
                continue
            memegang[kunci] = b["kelompok"]

            kelompok = KelompokMentoring.objects.filter(nama_kelompok=b["kelompok"]).order_by("pk").first()
            if kelompok is None:
                kelompok = KelompokMentoring.objects.create(nama_kelompok=b["kelompok"])
                if b["kelompok"] not in kelompok_baru:
                    kelompok_baru.add(b["kelompok"])
                    catatan.append(
                        f"Kelompok {b['kelompok']} hanya ada di CSV mentor; "
                        "dibuat tanpa link WhatsApp."
                    )

            profil = (
                Profile.objects.filter(role=Profile.ROLE_MENTOR, nama_lengkap__iexact=b["nama"])
                .order_by("pk")
                .first()
            )
            if profil is None:
                Profile.objects.create(
                    nama_lengkap=b["nama"], role=Profile.ROLE_MENTOR, kelompok=kelompok
                )
                dibuat += 1
            elif profil.kelompok_id is None:
                profil.kelompok = kelompok
                profil.save(update_fields=["kelompok"])
                ditempatkan += 1
            elif profil.kelompok_id != kelompok.pk:
                catatan.append(
                    f"{label}: sudah memegang {profil.kelompok}, dibiarkan."
                )

        self.stdout.write(
            f"Mentor CSV: {dibuat} dibuat, {ditempatkan} ditempatkan ke kelompok. "
            "Belum ber-NPM: isi lewat daftar Mentor di panel supaya bisa login SSO."
        )

    def tulis_catatan(self, catatan):
        if not catatan:
            return
        self.stdout.write(self.style.WARNING(f"{len(catatan)} catatan untuk dicek:"))
        for baris in catatan:
            self.stdout.write(self.style.WARNING(f"  - {baris}"))
