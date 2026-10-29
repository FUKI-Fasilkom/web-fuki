import datetime

from django.contrib.staticfiles import finders
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from amfm.models import AmfmBenefit, AmfmInfo, AmfmTimeline

# Foto kegiatan FUKI yang sudah ada di static, dipakai sebagai gambar contoh
# section "Apa itu AM-FM".
GAMBAR_CONTOH = "images/beranda1.jpg"


class Command(BaseCommand):
    help = (
        "Isi data contoh halaman AM-FM (info, benefit, timeline) supaya tampilannya "
        "bisa dicek saat terisi lengkap. Untuk lokal/QA saja: info AM-FM ditimpa dan "
        "baris contoh memakai update_or_create, jadi konten asli di server ikut tertimpa."
    )

    def handle(self, *args, **options):
        today = timezone.localdate()
        hari = datetime.timedelta(days=1)

        with transaction.atomic():
            info = AmfmInfo.get_solo()
            info.hero_judul = "AM-FM"
            info.hero_tagline = "#UnitePurposeAccelerateImpact"
            info.hero_deskripsi = (
                "Wadah mahasiswa baru Fasilkom UI untuk belajar, berkarya, dan bertumbuh "
                "bersama Forum Ukhuwah dan Kajian Islam."
            )
            info.apa_itu_deskripsi = (
                "AM-FM (Anggota Muda FUKI Muda) adalah program kaderisasi FUKI untuk mahasiswa "
                "baru Fasilkom UI. Selama program, anggota muda bergabung di salah satu biro "
                "atau departemen, ikut menjalankan program kerjanya, dan belajar langsung "
                "bersama pengurus FUKI."
            )
            info.tujuan = (
                "Membangun ukhuwah antar angkatan, mengenalkan ruang kontribusi di tiap "
                "birdept, dan menyiapkan anggota muda yang siap berdampak."
            )
            info.cta_deskripsi = (
                "Pilih birdept yang paling sesuai dengan minatmu dan mulai berkontribusi "
                "bersama FUKI Fasilkom UI."
            )
            # Sekali saja: menjalankan ulang perintah ini tidak menumpuk salinan gambar.
            if not info.apa_itu_gambar:
                with open(finders.find(GAMBAR_CONTOH), "rb") as berkas:
                    info.apa_itu_gambar.save("amfm-contoh.jpg", File(berkas), save=False)
            info.save()

            for i, (judul, desc) in enumerate([
                ("Relasi Lintas Angkatan",
                 "Kenal lebih dekat dengan kakak tingkat dan teman seangkatan dari berbagai jurusan di Fasilkom UI."),
                ("Pengalaman Berorganisasi",
                 "Terlibat langsung dalam program kerja birdept dan belajar bekerja dalam tim sejak semester awal."),
                ("Pengembangan Diri",
                 "Ikuti kurikulum tiap birdept, mulai dari desain, teknologi, kajian, hingga public relations."),
                ("Lingkungan yang Suportif",
                 "Bertumbuh bersama teman-teman yang saling mengingatkan dalam kebaikan dan semangat berkontribusi."),
            ]):
                AmfmBenefit.objects.update_or_create(judul=judul, defaults={"deskripsi": desc, "urutan": i})

            # Satu tahapan per status (selesai, berjalan, akan datang), seperti di design.
            for judul, desc, mulai, selesai in [
                ("Pendaftaran Dibuka", "Isi formulir pendaftaran AM-FM secara online.",
                 today - 7 * hari, None),
                ("Penutupan Pendaftaran", "Deadline pengumpulan formulir pendaftaran.",
                 today - hari, today + 3 * hari),
                ("Pengumuman", "Pengumuman status penerimaan dan birdept penempatan.",
                 today + 10 * hari, None),
                ("Kegiatan AM-FM", "Rangkaian kegiatan AM-FM bersama pengurus birdept penempatan.",
                 today + 17 * hari, today + 45 * hari),
            ]:
                AmfmTimeline.objects.update_or_create(
                    judul=judul,
                    defaults={
                        "deskripsi": desc,
                        "tanggal_mulai": mulai,
                        "tanggal_selesai": selesai,
                        "is_active": True,
                    },
                )

        self.stdout.write(self.style.SUCCESS("Data contoh AM-FM berhasil diisi."))
