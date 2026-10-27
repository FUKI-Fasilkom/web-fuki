from django import forms

from birdep.models import BirDep
from siwak.models import JURUSAN_CHOICES

from .models import Pendaftaran


class PendaftaranForm(forms.ModelForm):
    nama_lengkap = forms.CharField(label="Nama lengkap", disabled=True)
    npm = forms.CharField(label="NPM", disabled=True)
    jurusan = forms.ChoiceField(label="Program Studi", choices=JURUSAN_CHOICES, disabled=True)
    bukti_follow = forms.ImageField(
        label="Bukti Follow Instagram",
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png"}),
    )

    class Meta:
        model = Pendaftaran
        fields = ["jenis_kelamin", "kontak", "bukti_follow",
                  "pilihan_1", "pilihan_2", "motivasi", "portofolio"]
        labels = {"pilihan_1": "Pilihan birdept 1", "pilihan_2": "Pilihan birdept 2",
                  "motivasi": "Motivasi join AM-FM", "portofolio": "Link portofolio (opsional)"}
        widgets = {"jenis_kelamin": forms.RadioSelect(), "motivasi": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["jenis_kelamin"].choices = Pendaftaran._meta.get_field("jenis_kelamin").choices
        for name in ("nama_lengkap", "npm", "jurusan"):
            self.fields[name].initial = getattr(profile, name)
        for name in ("pilihan_1", "pilihan_2"):
            self.fields[name].queryset = BirDep.objects.filter(is_active=True)
            self.fields[name].empty_label = "Pilih Birdept"
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "amfm-input")

    def clean_bukti_follow(self):
        file = self.cleaned_data["bukti_follow"]
        if file.size > 2 * 1024 * 1024:
            raise forms.ValidationError("Ukuran bukti follow maksimal 2 MB.")
        if file.image.format not in {"JPEG", "PNG"}:
            raise forms.ValidationError("Bukti follow harus berupa gambar JPG atau PNG.")
        # Gunakan ekstensi sesuai isi gambar, bukan nama berkas dari browser.
        file.name = "bukti.jpg" if file.image.format == "JPEG" else "bukti.png"
        return file

    def clean(self):
        data = super().clean()
        if data.get("pilihan_1") and data.get("pilihan_1") == data.get("pilihan_2"):
            self.add_error("pilihan_2", "Pilihan birdept pertama dan kedua harus berbeda.")
        if not any(self.portfolio_birdept(data.get(name)) for name in ("pilihan_1", "pilihan_2")):
            data["portofolio"] = ""
        return data

    @staticmethod
    def portfolio_birdept(birdept):
        return birdept is not None and (
            birdept.slug.casefold() in {"itf", "medkre"}
            or birdept.nama.casefold() in {"itf", "medkre"}
        )
