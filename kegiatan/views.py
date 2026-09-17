from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.text import slugify
from .models import Kegiatan
import datetime

def kegiatan_page(request):
    today = datetime.date.today()
    active_tab = request.GET.get('tab', 'all')

    kegiatan_upcoming = []
    kegiatan_past = []

    if active_tab in ['all', 'upcoming']:
        kegiatan_upcoming = Kegiatan.objects.filter(tanggal__gte=today).order_by('tanggal')

    if active_tab in ['all', 'past']:
        kegiatan_past = Kegiatan.objects.filter(tanggal__lt=today).order_by('-tanggal')

    context = {
        'kegiatan_upcoming': kegiatan_upcoming,
        'kegiatan_past': kegiatan_past,
        'active_tab': active_tab,
    }
    return render(request, "kegiatan_list.html", context)


def kegiatan_detail(request, id):
    kegiatan = get_object_or_404(Kegiatan, pk=id)
    return render(request, "kegiatan_detail.html", {
        'kegiatan': kegiatan,
        'is_past': kegiatan.tanggal < datetime.date.today(),
    })


def _ics_escape(value):
    """Escape teks sesuai RFC 5545: koma, titik koma, dan backslash bermakna khusus."""
    if not value:
        return ''
    return (
        str(value)
        .replace('\\', '\\\\')
        .replace(';', '\\;')
        .replace(',', '\\,')
        .replace('\r\n', '\\n')
        .replace('\n', '\\n')
    )


def _ics_fold(line):
    """Lipat baris panjang sesuai RFC 5545 (maks 75 oktet, sambungan diawali spasi).

    Dihitung dalam byte, bukan karakter: satu huruf beraksen memakai dua oktet
    sehingga penghitungan per karakter bisa melewati batas tanpa terdeteksi.
    """
    raw = line.encode('utf-8')
    if len(raw) <= 75:
        return line

    potongan, mulai = [], 0
    while mulai < len(raw):
        batas = 75 if not potongan else 74  # baris sambungan kehilangan 1 oktet untuk spasi
        akhir = min(mulai + batas, len(raw))
        # Mundur agar tidak memotong di tengah karakter multibyte UTF-8.
        while akhir > mulai and akhir < len(raw) and (raw[akhir] & 0xC0) == 0x80:
            akhir -= 1
        potongan.append(raw[mulai:akhir].decode('utf-8'))
        mulai = akhir
    return '\r\n '.join(potongan)


def kegiatan_ics(request, id):
    """Berkas kalender untuk tombol 'Add To Calendar' di beranda.

    Disusun manual, bukan lewat pustaka, supaya tidak menambah dependensi.
    Waktu ditulis dalam UTC (sufiks Z) agar Google Calendar dan Outlook sama-sama
    menempatkannya di jam yang benar tanpa perlu blok VTIMEZONE.
    """
    kegiatan = get_object_or_404(Kegiatan, pk=id)

    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//FUKI Fasilkom UI//Kegiatan//ID',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        f'UID:kegiatan-{kegiatan.pk}@fuki.cs.ui.ac.id',
        f'DTSTAMP:{timezone.now().astimezone(datetime.timezone.utc):%Y%m%dT%H%M%SZ}',
        f'SUMMARY:{_ics_escape(kegiatan.judul)}',
    ]

    if kegiatan.start_time:
        start = timezone.make_aware(
            datetime.datetime.combine(kegiatan.tanggal, kegiatan.start_time)
        ).astimezone(datetime.timezone.utc)
        # Tanpa jam selesai, pakai durasi default 1 jam supaya event tidak nol menit.
        end_local = kegiatan.end_time or (
            datetime.datetime.combine(kegiatan.tanggal, kegiatan.start_time)
            + datetime.timedelta(hours=1)
        ).time()
        end = timezone.make_aware(
            datetime.datetime.combine(kegiatan.tanggal, end_local)
        ).astimezone(datetime.timezone.utc)
        lines.append(f'DTSTART:{start:%Y%m%dT%H%M%SZ}')
        lines.append(f'DTEND:{end:%Y%m%dT%H%M%SZ}')
    else:
        # Tanpa jam mulai, catat sebagai all-day event. DTEND bersifat eksklusif,
        # jadi harus H+1 agar tidak tampil sebagai event tanpa durasi.
        lines.append(f'DTSTART;VALUE=DATE:{kegiatan.tanggal:%Y%m%d}')
        lines.append(
            f'DTEND;VALUE=DATE:{kegiatan.tanggal + datetime.timedelta(days=1):%Y%m%d}'
        )

    if kegiatan.deskripsi:
        lines.append(f'DESCRIPTION:{_ics_escape(kegiatan.deskripsi)}')
    if kegiatan.lokasi:
        lines.append(f'LOCATION:{_ics_escape(kegiatan.lokasi)}')

    lines += ['END:VEVENT', 'END:VCALENDAR']

    isi = '\r\n'.join(_ics_fold(baris) for baris in lines)
    response = HttpResponse(isi, content_type='text/calendar; charset=utf-8')
    nama_berkas = slugify(kegiatan.judul) or f'kegiatan-{kegiatan.pk}'
    response['Content-Disposition'] = f'attachment; filename="{nama_berkas}.ics"'
    return response
