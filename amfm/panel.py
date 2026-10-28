"""Deklarasi sumber panel AMFM; helper daftar berasal dari mesin bersama."""
from main.panel import Kolom, Sumber
from .models import AmfmBenefit, AmfmTimeline, Pendaftaran
from .panel_forms import BenefitForm, TimelineForm

PENDAFTAR = Sumber(
    slug="pendaftar", bagian="amfm", label="Pendaftar", label_jamak="List Pendaftar",
    deskripsi="Jawaban formulir AM-FM.", model=Pendaftaran, form=None,
    kolom=(Kolom("Nama", lambda o: o.nama_lengkap, utama=True),),
    pencarian=("nama_lengkap", "npm"), boleh_tambah=False, boleh_ubah=False, boleh_hapus=False,
    queryset=lambda: Pendaftaran.objects.select_related("pilihan_1", "pilihan_2", "penempatan").order_by("-created_at", "-pk"),
)

KONTEN = {
    "benefit": Sumber(
        slug="benefit", bagian="konten", label="Benefit", label_jamak="Benefit AM-FM",
        deskripsi="Kartu benefit di halaman informasi.", model=AmfmBenefit, form=BenefitForm,
        kolom=(Kolom("Judul", lambda o: o.judul, utama=True), Kolom("Urutan", lambda o: o.urutan)),
    ),
    "timeline": Sumber(
        slug="timeline", bagian="konten", label="Timeline", label_jamak="Timeline AM-FM",
        deskripsi="Tahapan kegiatan di halaman informasi.", model=AmfmTimeline, form=TimelineForm,
        kolom=(Kolom("Judul", lambda o: o.judul, utama=True), Kolom("Tanggal mulai", lambda o: o.tanggal_mulai, "tanggal"), Kolom("Aktif", lambda o: o.is_active, "bool")),
    ),
}
