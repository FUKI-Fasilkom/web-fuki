# Panel pengelola AM-FM

Panel khusus berada di `/amfm/admin/`, login di `/amfm/admin/login/`.
Menggunakan sesi dan backend autentikasi situs yang sama. Peserta tetap masuk
melalui SSO UI di `/amfm/daftar/`.

## Akun dan permission

Buat akun Django dan group **Pengelola AM-FM** melalui Django admin yang sudah
ada, lalu masukkan akun pengelola ke group itu. Akun AM-FM tidak memerlukan
`is_staff`; flag itu membuka panel SIWAK, jadi jangan diberikan hanya untuk AM-FM.
Tidak ada password bawaan atau akun otomatis.

Permission yang diperlukan:

| Kebutuhan | Permission |
| --- | --- |
| Baca dashboard, daftar, detail, bukti | `amfm.view_pendaftaran` atau `amfm.change_pendaftaran` |
| Simpan keputusan dan bulk status | `amfm.change_pendaftaran` |
| Hapus pendaftar | `amfm.delete_pendaftaran` (ditambah akses baca panel) |
| Pengaturan dan konten landing | `amfm.change_amfminfo` (ditambah akses baca panel) |
| Benefit | `view/add/change/delete_amfmbenefit`, sesuai tindakan |
| Timeline | `view/add/change/delete_amfmtimeline`, sesuai tindakan |

Akun hanya-baca cukup diberi `view_pendaftaran`. Semua tindakan diperiksa lagi
di server, termasuk endpoint unduhan dan POST, bukan hanya menyembunyikan tombol.
Login Akun Khusus bersama juga menerima pengelola AM-FM. Urutan landing role lama
tetap dipertahankan; login khusus AM-FM mendarat langsung ke dashboard AM-FM.

## Aturan seleksi

- Status awal Menunggu; Diterima wajib memiliki penempatan dari pilihan 1 atau 2.
- Menunggu/Ditolak menghapus penempatan.
- Bulk hanya memengaruhi ID yang dicentang, maksimal 250 per permintaan, dan
  memerlukan konfirmasi. Pilihan tidak otomatis mencakup halaman berikutnya.
- Untuk bulk Diterima, pilih satu birdept yang menjadi pilihan setiap peserta.
  Jika penempatan dikosongkan, gunakan penempatan masing-masing yang sudah ada.
- Satu baris tidak valid membatalkan seluruh batch. Semua baris dikunci dan
  divalidasi sebelum perubahan disimpan.
- Django admin memakai aturan seleksi yang sama; bulk Diterima di Django admin
  memerlukan penempatan yang sudah disimpan dari detail.
- Hapus memerlukan halaman konfirmasi dan POST. Akun pengguna tetap ada; berkas
  bukti dihapus oleh signal `post_delete` setelah transaksi commit.

Dashboard menghitung orang untuk total/status. Grafik per birdept menghitung
pilihan 1 dan 2, sehingga jumlah seluruh birdept adalah dua kali jumlah peserta.
Filter birdept cocok pada salah satu pilihan. Semua statistik dihitung dari DB.

## Tampilan dan sumber konfigurasi

Acuan Figma: https://www.figma.com/design/QorGH2KfHvHGatYUmIT0hS/Pabrik-Lefi-2?node-id=0-1

Kerangka AM-FM menggunakan hero, navbar, footer, font, dan token situs.
`main/panel.py` tetap menjadi sumber `PanelForm`, `Sumber`, `Kolom`, helper sel,
dan ukuran pagination. Template khusus AM-FM mengikuti tab dan kartu Figma tanpa
mengubah kerangka sidebar SIWAK/KI. Ikon statistik dan avatar disimpan lokal dari
Figma; tidak ada ketergantungan pada URL aset sementara.

Pengaturan tetap berada di singleton `AmfmInfo`; pengubahan jadwal memakai kunci
baris yang sama dengan pengiriman formulir. Jadwal menggunakan zona Asia/Jakarta.
Panel konten mengelola hero, tentang, tujuan, CTA, benefit, dan timeline.

Model sekarang menyimpan satu bukti follow gabungan, dua pilihan wajib, dan
motivasi maksimal 50 karakter. Panel menampilkan data sesuai kontrak tersebut;
tidak menambahkan berkas kedua atau mengubah formulir peserta secara diam-diam.
Bukti hanya tersedia lewat endpoint terotorisasi, tidak melalui URL storage.
Panel memakai `no-store`, `noindex`, serta pengecualian Clarity.

## Verifikasi lokal

Gunakan interpreter dari environment proyek (contoh `env/bin/python`), PostgreSQL,
dan konfigurasi `.env` sebagaimana README utama. Tidak ada migrasi baru untuk panel.

```sh
env/bin/python manage.py test amfm siwak ki main
env/bin/python manage.py test
env/bin/python manage.py makemigrations --check --dry-run
env/bin/python manage.py check --deploy --fail-level ERROR
```

Periksa login, dashboard kosong/berisi, filter dan pagination, detail, keputusan,
bulk gagal/sukses, pengaturan, CRUD konten, dan konfirmasi hapus. Periksa desktop
1440px, tablet 768px, dan ponsel 390px. Tabel di ponsel bergulir di dalam kartu;
halaman keseluruhan tidak boleh melebar.
