from datetime import datetime, timezone
import json
import os

import requests
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST

def health_check(request):
    return JsonResponse({"status": "ok"})

def beranda(request):
    return render(request, 'beranda.html')

def hubungi_kami(request):
    return render(request, 'hubungi_kami.html')

def lapor(request):
    return render(request, 'lapor.html')


# Discord embed accent per jenis laporan.
_EMBED_COLORS = {
    'Bug': 0xE74C3C,         # merah
    'Isi Konten': 0x3498DB,  # biru
}


@require_POST
def lapor_submit(request):
    """Forward a bug report to the FUKI Discord channel via webhook.

    The webhook URL stays on the server -- the browser only ever talks to this
    endpoint, so the URL never ends up in page source.
    """
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        return JsonResponse(
            {'ok': False, 'error': 'Webhook belum dikonfigurasi.'}, status=500
        )

    email = (request.POST.get('email') or '').strip()
    nama = (request.POST.get('nama') or '').strip()
    judul = (request.POST.get('judul') or '').strip()
    jenis = (request.POST.get('jenis') or '').strip()
    deskripsi = (request.POST.get('deskripsi') or '').strip()

    # Email and nama are optional -- a report is still actionable anonymously.
    if not (judul and deskripsi and jenis in _EMBED_COLORS):
        return JsonResponse(
            {'ok': False, 'error': 'Mohon lengkapi seluruh isian wajib.'}, status=400
        )

    embed = {
        'title': judul[:256],
        'color': _EMBED_COLORS[jenis],
        'fields': [
            {'name': 'Jenis Laporan', 'value': jenis, 'inline': True},
            {'name': 'Nama', 'value': nama or 'Anonymous', 'inline': True},
            {'name': 'Email', 'value': email or 'Anonymous', 'inline': False},
            {'name': 'Deskripsi Masalah', 'value': deskripsi[:1024], 'inline': False},
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'footer': {'text': 'Laporkan Masalah - web FUKI Fasilkom UI'},
    }

    files = {}
    gambar = request.FILES.get('gambar')
    if gambar:
        # Referencing the attachment by name makes Discord render it inside the
        # embed instead of dangling below it.
        embed['image'] = {'url': f'attachment://{gambar.name}'}
        files['files[0]'] = (gambar.name, gambar.read(), gambar.content_type)

    payload = {'embeds': [embed]}

    role_id = os.getenv('DISCORD_ROLE_ID')
    if role_id:
        payload['content'] = f'<@&{role_id}>'
        # Webhooks parse every mention in `content` by default; naming the role
        # explicitly keeps the ping working even if that default changes, and
        # blocks @everyone/@here from ever slipping through report text.
        payload['allowed_mentions'] = {'parse': [], 'roles': [role_id]}

    files['payload_json'] = (None, json.dumps(payload), 'application/json')

    try:
        response = requests.post(webhook_url, files=files, timeout=15)
        response.raise_for_status()
    except requests.RequestException:
        return JsonResponse(
            {'ok': False, 'error': 'Gagal mengirim laporan. Coba lagi nanti.'},
            status=502,
        )

    return JsonResponse({'ok': True})
