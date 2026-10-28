"""Statistik peserta dihitung dari sumber yang sama dengan daftar seleksi."""
from collections import defaultdict
from django.db.models import Count, Q
from birdep.models import BirDep
from amfm.models import Pendaftaran
from .seleksi import STATUS


def statistik_panel():
    qs = Pendaftaran.objects.all()
    total = qs.aggregate(total=Count("pk"), **{
        status: Count("pk", filter=Q(status=status)) for status in STATUS
    })
    # Dua agregasi terpisah menghindari perkalian baris saat menggabungkan
    # dua reverse FK sekaligus. Jumlah query tetap, berapa pun jumlah peserta.
    counts = defaultdict(lambda: defaultdict(int))
    for field in ("pilihan_1_id", "pilihan_2_id"):
        for row in qs.order_by().values(field, "status").annotate(jumlah=Count("pk")):
            counts[row[field]][row["status"]] += row["jumlah"]
    maksimum = max((sum(values.values()) for values in counts.values()), default=1) or 1
    birdept = []
    for b in BirDep.objects.filter(Q(is_active=True) | Q(pk__in=counts)).order_by("urutan", "nama"):
        values = counts[b.pk]
        birdept.append({"obj": b, "total": sum(values.values()), "bagian": [
            {"status": status, "label": label, "jumlah": values[status], "lebar": f"{values[status] * 100 / maksimum:.4f}"}
            for status, label in STATUS.items()
        ]})
    n = total["total"] or 1
    batas_1 = total["menunggu"] * 100 / n
    batas_2 = (total["menunggu"] + total["diterima"]) * 100 / n
    return {
        "total": total, "birdept": birdept,
        "kartu": [
            {"label": "Jumlah Pendaftar", "jumlah": total["total"], "ikon": "users"},
            *[{"label": label, "jumlah": total[status], "ikon": ikon} for (status, label), ikon in zip(STATUS.items(), ("clock", "circle-check", "circle-x"))],
        ],
        "legenda": [{"status": status, "label": label, "jumlah": total[status]} for status, label in STATUS.items()],
        "donut": f"conic-gradient(#F8BA47 0% {batas_1:.4f}%, #0DA582 {batas_1:.4f}% {batas_2:.4f}%, #EB6D68 {batas_2:.4f}% 100%)" if total["total"] else "#e5e7eb",
    }
