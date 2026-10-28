import re

from django.db import migrations, models


def pindahkan_kontak(apps, schema_editor):
    Pendaftaran = apps.get_model("amfm", "Pendaftaran")
    for peserta in Pendaftaran.objects.using(schema_editor.connection.alias).all().iterator():
        kontak = peserta.kontak.strip()
        if kontak.lower().startswith("id line:"):
            peserta.id_line = kontak.partition(":")[2].strip()
        elif re.fullmatch(r"(?:\+62|62|0)\d[\d .-]*", kontak):
            peserta.nomor_whatsapp = kontak
        else:
            # Isian lama tidak bertipe; simpan utuh sebagai ID LINE agar tidak hilang.
            peserta.id_line = kontak
        peserta.save(update_fields=["nomor_whatsapp", "id_line"])


class Migration(migrations.Migration):
    dependencies = [("amfm", "0004_remove_pendaftaran_amfm_pilihan_berbeda")]

    operations = [
        migrations.AddField(
            model_name="pendaftaran", name="nomor_whatsapp",
            field=models.CharField(blank=True, max_length=100, verbose_name="Nomor WhatsApp"),
        ),
        migrations.AddField(
            model_name="pendaftaran", name="id_line",
            field=models.CharField(blank=True, max_length=100, verbose_name="ID LINE"),
        ),
        migrations.RunPython(pindahkan_kontak, migrations.RunPython.noop),
        migrations.RemoveField(model_name="pendaftaran", name="kontak"),
    ]
