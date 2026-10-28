"""Data registrasi palsu untuk mencoba panel tanpa autentikasi SSO peserta."""
from io import BytesIO

from PIL import Image, ImageDraw
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from amfm.models import Pendaftaran
from birdep.models import BirDep

GRUP_DEMO = "Demo Pendaftar AM-FM"


class Command(BaseCommand):
    help = "Tambahkan pendaftar contoh lokal; data dan keputusan yang sudah ada tidak ditimpa."

    def add_arguments(self, parser):
        parser.add_argument("--jumlah", type=int, default=12, help="Jumlah total contoh yang diinginkan (1–100).")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Data contoh hanya untuk lokal: jalankan dengan DEBUG=True.")
        if settings.AWS_STORAGE_BUCKET_NAME:
            raise CommandError("Gunakan storage lokal (AWS_STORAGE_BUCKET_NAME kosong) untuk data contoh.")
        jumlah = options["jumlah"]
        if not 1 <= jumlah <= 100:
            raise CommandError("Jumlah harus antara 1 dan 100.")
        files = []
        try:
            with transaction.atomic():
                grup, _ = Group.objects.get_or_create(name=GRUP_DEMO)
                birdept = list(BirDep.objects.filter(is_active=True)[:2])
                for slug, nama in (("demo-amfm-itf", "Demo ITF"), ("demo-amfm-medkre", "Demo Medkre")):
                    if len(birdept) == 2:
                        break
                    obj, _ = BirDep.objects.get_or_create(slug=slug, defaults={"nama": nama, "logo_filename": ""})
                    if obj not in birdept:
                        birdept.append(obj)
                dibuat = 0
                for i in range(1, jumlah + 1):
                    username = f"demo-amfm-{i:03d}"
                    user, baru = get_user_model().objects.get_or_create(username=username, defaults={"is_active": False})
                    if baru:
                        user.set_unusable_password()
                        user.save(update_fields=["password"])
                        user.groups.add(grup)
                    elif not user.groups.filter(pk=grup.pk).exists():
                        raise CommandError(f"Akun {username} bukan milik seed demo; tidak diubah.")
                    if Pendaftaran.objects.filter(user=user).exists():
                        continue
                    npm = f"99000000{i:04d}"
                    if Pendaftaran.objects.filter(npm=npm).exists():
                        raise CommandError(f"NPM demo {npm} sudah dipakai data lain; tidak diubah.")
                    status = ("menunggu", "diterima", "ditolak")[(i - 1) % 3]
                    first, second = birdept[i % 2], birdept[(i + 1) % 2]
                    obj = Pendaftaran(
                        user=user, npm=npm, nama_lengkap=f"Peserta Contoh AM-FM {i:02d}",
                        jurusan=("IK", "SI")[i % 2], jenis_kelamin=("L", "P")[i % 2],
                        id_line="demo-amfm", pilihan_1=first, pilihan_2=second,
                        motivasi="Belajar dan berkontribusi bersama FUKI.",
                        portofolio="https://example.com/portfolio-demo", status=status,
                        penempatan=first if status == "diterima" else None,
                    )
                    image = Image.new("RGB", (640, 360), "#F2E5BB")
                    ImageDraw.Draw(image).text((32, 32), "DEMO AM-FM\nContoh bukti follow untuk pengujian lokal", fill="#12284C")
                    buffer = BytesIO()
                    image.save(buffer, format="PNG")
                    obj.bukti_follow.save("bukti-demo.png", ContentFile(buffer.getvalue()), save=False)
                    files.append(obj.bukti_follow)
                    obj.bukti_follow_2.save("bukti-demo.png", ContentFile(buffer.getvalue()), save=False)
                    files.append(obj.bukti_follow_2)
                    obj.full_clean()
                    obj.save()
                    dibuat += 1
        except Exception:
            # Berkas tidak ikut rollback transaksi PostgreSQL.
            for file in files:
                file.delete(save=False)
            raise
        self.stdout.write(self.style.SUCCESS(
            f"{dibuat} pendaftar contoh ditambahkan. Data lama dipertahankan. "
            "Buka /amfm/admin/ dan masuk dengan akun pengelola/superuser Anda."
        ))
