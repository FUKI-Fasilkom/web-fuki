from django.shortcuts import render
from django.http import Http404
from datetime import date

# Data Dummy Global (Mock Database)
DUMMY_KAJIAN = [
    {
        'id': 1,
        'judul': 'Manajemen Waktu Islami',
        'penulis': 'Ust. Abdullah', # Konsistensi field 'sumber' atau 'penulis'
        'sumber': 'Ust. Abdullah',
        'tanggal': date(2025, 1, 1),
        'image': 'https://placehold.co/600x400/png',
        'content': """
            <p class="mb-4">Waktu adalah modal utama manusia. Dalam Islam, waktu sangat dihargai. Allah SWT bersumpah demi waktu dalam surat Al-'Asr, menandakan betapa pentingnya kita memanfaatkannya dengan baik.</p>
            <p class="mb-4">Manajemen waktu islami bukan sekadar menjadi produktif secara duniawi, tetapi bagaimana menyelaraskan aktivitas dunia dengan tujuan akhirat. Shalat lima waktu adalah tonggak utama manajemen waktu seorang muslim.</p>
            <p>Mari kita mulai menata jadwal harian kita dengan memprioritaskan kewajiban kepada Allah, niscaya urusan dunia akan mengikuti dengan keberkahan.</p>
        """
    },
    {
        'id': 2,
        'judul': 'Pentingnya Menuntut Ilmu',
        'penulis': 'Ust. Fulan',
        'sumber': 'Ust. Fulan',
        'tanggal': date(2025, 1, 5),
        'image': '',
        'content': """
            <p class="mb-4">Menuntut ilmu adalah kewajiban bagi setiap muslim. Ilmu adalah cahaya yang menerangi jalan kehidupan kita menuju ridha Allah SWT.</p>
            <p>Tanpa ilmu, seseorang bisa tersesat dalam beribadah. Sebagaimana Imam Bukhari berkata, 'Berilmu sebelum berkata dan beramal'.</p>
        """
    },
    {
        'id': 3,
        'judul': 'Sejarah Peradaban Islam',
        'penulis': 'Dr. Siti Aminah',
        'sumber': 'Dr. Siti Aminah',
        'tanggal': date(2025, 1, 12),
        'image': 'https://placehold.co/600x400/orange/white',
        'content': """
            <p class="mb-4">Sejarah membuktikan bahwa Islam pernah memimpin peradaban dunia. Dari Andalusia hingga Baghdad, ilmu pengetahuan berkembang pesat di bawah naungan Islam.</p>
            <p>Kita perlu mempelajari sejarah ini bukan untuk bernostalgia semata, melainkan untuk mengambil ibrah dan semangat untuk membangkitkan kembali kejayaan umat melalui ilmu dan akhlak.</p>
        """
    },
    {
        'id': 4,
        'judul': 'Adab Terhadap Orang Tua',
        'penulis': 'Ust. Khalid',
        'sumber': 'Ust. Khalid',
        'tanggal': date(2025, 1, 15),
        'image': 'https://placehold.co/600x400/green/white',
        'content': """
            <p class="mb-4">Ridha Allah terletak pada ridha orang tua. Pembahasan kali ini sangat penting mengingat banyaknya fenomena dekadensi moral di kalangan remaja terhadap orang tua mereka.</p>
        """
    },
    {
        'id': 5,
        'judul': 'Fiqih Muamalah Dasar',
        'penulis': 'Ust. Yusuf',
        'sumber': 'Ust. Yusuf',
        'tanggal': date(2025, 1, 20),
        'image': '',
        'content': """
            <p class="mb-4">Dalam berdagang dan berbisnis, seorang muslim terikat dengan aturan syariat. Menghindari riba, gharar, dan maysir adalah prinsip dasar yang harus dipegang teguh.</p>
        """
    },
    {
        'id': 6,
        'judul': 'Tafsir Surat Al-Fatihah',
        'penulis': 'Syeikh Ahmad',
        'sumber': 'Syeikh Ahmad',
        'tanggal': date(2025, 1, 25),
        'image': 'https://placehold.co/600x400/blue/white',
        'content': """
            <p class="mb-4">Al-Fatihah adalah Ummul Kitab. Memahami tafsirnya adalah kunci kekhusyukan dalam shalat kita.</p>
        """
    },
]

def blog_kajian_page(request):
    context = {
        'kajian_list': DUMMY_KAJIAN
    }
    return render(request, 'blog_kajian.html', context)

def kajian_detail(request, id):
    # Cari artikel berdasarkan ID
    # next() akan mencari item pertama yang id-nya cocok
    article = next((item for item in DUMMY_KAJIAN if item['id'] == id), None)
    
    if not article:
        # Jika ID tidak ditemukan, tampilkan 404 atau redirect (di sini saya pakai 404 standar)
        raise Http404("Kajian tidak ditemukan")

    # Untuk sidebar, kita ambil semua kajian KECUALI yang sedang dibuka (agar tidak duplikat)
    # Lalu kita ambil 3 teratas sebagai rekomendasi
    sidebar_list = [k for k in DUMMY_KAJIAN if k['id'] != id][:3]

    context = {
        'article': article,
        'sidebar_list': sidebar_list
    }
    return render(request, 'kajian_detail.html', context)