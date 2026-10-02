"""Form panel Kontrol Internal.

Fieldnya disamakan dengan form Kegiatan di Django admin (`kegiatan/admin.py`
tidak membatasi `fields`, jadi admin menampilkan seluruh field yang bisa
disunting, dalam urutan model). Yang ditambahkan di sini hanya label dan
penjelasan: pengurus KI tidak perlu tahu nama field di model untuk mengisinya.

Gaya isiannya datang dari `PanelForm` (`main/panel.py`), sama dengan panel SIWAK.
"""

from django import forms

from kegiatan.models import Kegiatan
from main.panel import PanelForm


class KegiatanPanelForm(PanelForm):
    class Meta:
        model = Kegiatan
        # Sama dengan yang tampil di Django admin, urutan mengikuti model.
        fields = [
            "judul",
            "deskripsi",
            "kategori",
            "tipe",
            "birdep",
            "tanggal",
            "start_time",
            "end_time",
            "lokasi",
            "link_lokasi",
            "contact",
            "link_registrasi",
        ]
        labels = {
            "judul": "Judul kegiatan",
            "deskripsi": "Deskripsi",
            "kategori": "Kategori",
            "tipe": "Penyelenggara",
            "birdep": "Biro / Departemen",
            "tanggal": "Tanggal",
            "start_time": "Jam mulai",
            "end_time": "Jam selesai",
            "lokasi": "Lokasi",
            "link_lokasi": "Link lokasi",
            "contact": "Kontak",
            "link_registrasi": "Link pendaftaran",
        }
        help_texts = {
            "deskripsi": "Tampil di kartu kegiatan dan halaman detailnya.",
            "kategori": "Menentukan tab filter mana yang memuat kegiatan ini di beranda.",
            "tipe": (
                "Menentukan logo yang tampil di kartu kegiatan. FUKI / General memakai "
                "logo FUKI, SIWAK memakai logo SIWAK-NG, dan Biro / Departemen memakai "
                "logo BirDep yang dipilih di bawah."
            ),
            "birdep": "Wajib diisi kalau penyelenggaranya Biro / Departemen; selain itu biarkan kosong.",
            "start_time": "Opsional. Dikosongkan berarti jam tidak ditampilkan sama sekali.",
            "end_time": "Opsional. Hanya dipakai kalau jam mulai sudah diisi.",
            "lokasi": "Opsional. Dikosongkan berarti baris lokasi tidak ditampilkan.",
            "link_lokasi": "Opsional. Kalau diisi, lokasi di atas jadi tautan ke peta ini.",
            "contact": "Opsional. Nomor atau nama narahubung kegiatan.",
            "link_registrasi": (
                "Opsional. Kalau diisi, tombol “Daftar Sekarang” muncul di halaman detail "
                "selama kegiatannya belum berlalu."
            ),
        }
        widgets = {
            "deskripsi": forms.Textarea(attrs={"rows": 5}),
            "link_lokasi": forms.URLInput(),
            "link_registrasi": forms.URLInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # BirDep hanya relevan untuk tipe "birdep", jadi pilihannya dibatasi ke
        # yang masih aktif supaya daftar lama tidak ikut muncul.
        self.fields["birdep"].queryset = (
            self.fields["birdep"].queryset.filter(is_active=True).order_by("urutan", "nama")
        )
        self.fields["birdep"].empty_label = "— Bukan Biro / Departemen —"
