from django.core.exceptions import ValidationError
from django.db import models
from django.templatetags.static import static
from django.urls import reverse
from django.utils.functional import cached_property

LOGO_FUKI = 'images/Logo-FUKI-Biru.png'


class Kegiatan(models.Model):
    # Label harus sama persis dengan tab filter di beranda.
    KATEGORI_CHOICES = [
        ('maba', 'Kegiatan Maba'),
        ('kajian', 'Kajian & Syiar'),
        ('sosial', 'Sosial'),
        ('internal', 'Internal'),
    ]

    # Penyelenggara menentukan logo yang tampil di kartu kegiatan, menggantikan
    # poster yang dulu diunggah per kegiatan.
    TIPE_FUKI = 'fuki'
    TIPE_SIWAK = 'siwak'
    TIPE_BIRDEP = 'birdep'
    TIPE_CHOICES = [
        (TIPE_FUKI, 'FUKI / General'),
        (TIPE_SIWAK, 'SIWAK'),
        (TIPE_BIRDEP, 'Biro / Departemen'),
    ]

    judul = models.CharField(max_length=200, verbose_name="Judul Kegiatan")
    deskripsi = models.TextField(verbose_name="Deskripsi Kegiatan", blank=True)
    kategori = models.CharField(
        max_length=20, choices=KATEGORI_CHOICES, default='kajian',
        verbose_name="Kategori Kegiatan",
    )

    # penyelenggara (sumber logo kartu)
    tipe = models.CharField(
        max_length=10, choices=TIPE_CHOICES, default=TIPE_FUKI,
        verbose_name="Penyelenggara Kegiatan",
    )
    birdep = models.ForeignKey(
        'birdep.BirDep', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='kegiatan_set', verbose_name="Biro / Departemen",
        help_text="Wajib diisi bila penyelenggaranya Biro / Departemen.",
    )

    # waktu dan tempat
    tanggal = models.DateField(verbose_name="Tanggal Kegiatan")
    start_time = models.TimeField(null=True, blank=True, verbose_name="Jam Mulai")
    end_time = models.TimeField(null=True, blank=True, verbose_name="Jam Selesai")

    lokasi = models.CharField(max_length=200, blank=True, default='', verbose_name="Lokasi Kegiatan")
    link_lokasi = models.CharField(verbose_name="Link lokasi kegiatan", null=True, blank=True)

    contact = models.CharField(verbose_name="Contact Kegiatan", null=True, blank=True)
    link_registrasi = models.CharField(verbose_name="Link pendaftaran kegiatan", null=True, blank=True)

    class Meta:
        ordering = ['tanggal']

    def __str__(self):
        return self.judul

    def clean(self):
        # Tanpa ini, tipe 'birdep' tanpa BirDep akan jatuh ke logo FUKI tanpa
        # pengurus sadar bahwa pilihannya tidak tersimpan.
        if self.tipe == self.TIPE_BIRDEP and not self.birdep_id:
            raise ValidationError({'birdep': "Pilih Biro / Departemen penyelenggaranya."})

    def get_absolute_url(self):
        return reverse('kegiatan:detail', kwargs={'id': self.pk})

    @cached_property
    def logo_url(self):
        """URL logo yang tampil di kartu kegiatan; satu sumber untuk ketiga template.

        Selalu mengembalikan URL, jadi kartu tidak pernah kehilangan gambarnya:
        tipe yang logonya belum tersedia jatuh ke logo FUKI, bukan gambar rusak.

        Di-cache per instance karena tipe SIWAK membaca SiwakInfo dari database,
        sedangkan template memanggilnya lebih dari sekali per kartu.
        """
        # logo_filename diperiksa, bukan BirDep.logo_url: BirDep tanpa berkas logo
        # harus jatuh ke logo FUKI biru yang bercahaya, persis seperti kartunya di
        # halaman Biro & Departemen.
        if self.tipe == self.TIPE_BIRDEP and self.birdep_id and self.birdep.logo_filename:
            return static(self.birdep.logo_url)
        if self.tipe == self.TIPE_SIWAK:
            # Gambar yang sama dengan section "Apa itu SIWAK-NG". Diimpor di sini,
            # bukan di level modul, karena app siwak dimuat setelah kegiatan.
            from siwak.models import SiwakInfo

            info = SiwakInfo.objects.first()
            if info and info.apa_itu_gambar:
                return info.apa_itu_gambar.url
        return static(LOGO_FUKI)

    @property
    def logo_bercahaya(self):
        """True bila logonya FUKI biru, yang tenggelam di atas kartu navy.

        Aturan dan perlakuan cahayanya sama dengan kartu unit di halaman
        Biro & Departemen (`birdep/components/kartu_unit.html`).
        """
        return self.logo_url == static(LOGO_FUKI)

    @property
    def penyelenggara(self):
        """Nama penyelenggara, dipakai sebagai teks alternatif logonya."""
        if self.tipe == self.TIPE_BIRDEP and self.birdep_id:
            return self.birdep.nama
        return 'SIWAK' if self.tipe == self.TIPE_SIWAK else 'FUKI'
