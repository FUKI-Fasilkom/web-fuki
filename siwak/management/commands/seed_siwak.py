import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from siwak.models import (
    EventRSVP,
    FAQMentoring,
    KelompokMentoring,
    KetuaSiwak,
    MentoringBenefit,
    MentoringTujuan,
    Mentor,
    PesertaMentoring,
    SistemMentoring,
    SiwakEvent,
    SiwakInfo,
    TimelineEvent,
    Tugas,
)


class Command(BaseCommand):
    help = "Isi data contoh untuk section SIWAK supaya halaman tidak kosong saat QA/demo."

    def handle(self, *args, **options):
        today = timezone.localdate()

        info = SiwakInfo.get_solo()
        info.hero_judul = "SIWAK-NG"
        info.hero_deskripsi = (
            "Sistem Informasi Wawasan Almamater dan Kaderisasi — masa pengenalan dan mentoring "
            "keislaman untuk mahasiswa baru Fasilkom UI."
        )
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
            tipe="pre_event",
            defaults=dict(
                judul="Pre-Event SIWAK",
                deskripsi="Sesi pembukaan dan pengenalan kelompok mentoring.",
                tanggal=today + datetime.timedelta(days=10),
                lokasi="Auditorium Fasilkom UI",
                urutan=1,
            ),
        )
        SiwakEvent.objects.update_or_create(
            tipe="main_event",
            defaults=dict(
                judul="Main Event SIWAK",
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
            defaults={"jawaban": "Gunakan menu 'Cari Kelompok' atau hubungi CP Fakultas yang tertera.", "urutan": 1},
        )

        mentor1, _ = Mentor.objects.get_or_create(nama="Kak Ahmad")
        mentor2, _ = Mentor.objects.get_or_create(nama="Kak Fatimah")
        kelompok1, _ = KelompokMentoring.objects.get_or_create(
            nama_kelompok="Kelompok 1",
            defaults={"link_grup": "https://chat.whatsapp.com/contoh-link-kelompok-1"},
        )
        kelompok1.mentors.set([mentor1, mentor2])

        PesertaMentoring.objects.update_or_create(
            nama_lengkap="Marwa Muhlashon", jurusan="SI",
            defaults={"kelompok": kelompok1},
        )

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

        self.stdout.write(self.style.SUCCESS("Data contoh SIWAK berhasil diisi."))