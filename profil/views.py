from django.shortcuts import render

from birdep.models import PengurusInti

# Create your views here.


def tentang_fuki(request):
    # Ketua & Wakil diambil dari birdep.PengurusInti, BUKAN dari profil.Fungsionaris:
    # model legacy itu kosong (0 baris) sehingga grid fungsionaris halaman lama
    # tidak pernah menampilkan apa pun.
    #
    # Dipilih lewat awalan jabatan, bukan lewat `urutan`: urutan 1-2 saat ini
    # adalah Dewan Permusyawaratan dan Ketua, jadi [:2] justru salah orang.
    # istartswith supaya tetap benar bila ditulis "Ketua Umum"/"Wakil Ketua Umum";
    # filter kategori='pi' mencegah "Ketua KI" dan "Ketua MDC" ikut terjaring.
    pengurus_inti = PengurusInti.objects.filter(kategori='pi', is_active=True)
    ketua = pengurus_inti.filter(jabatan__istartswith='ketua').first()
    wakil = pengurus_inti.filter(jabatan__istartswith='wakil').first()

    return render(request, 'profil.html', {
        'sorotan': [p for p in (ketua, wakil) if p],
    })
