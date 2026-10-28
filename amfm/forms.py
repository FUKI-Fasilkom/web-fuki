from django import forms

from birdep.models import BirDep

from .models import Pendaftaran


class PendaftaranForm(forms.ModelForm):
    nama_lengkap = forms.CharField(label="Nama lengkap", disabled=True)
    npm = forms.CharField(label="NPM", disabled=True)
    jurusan = forms.CharField(label="Program Studi", disabled=True)
    bukti_follow = forms.ImageField(
        label="Bukti Follow Instagram 1", required=False,
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png", "class": "sr-only"}),
    )
    bukti_follow_2 = forms.ImageField(
        label="Bukti Follow Instagram 2 (opsional)", required=False,
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png", "class": "sr-only"}),
    )

    class Meta:
        model = Pendaftaran
        fields = ["jenis_kelamin", "kontak", "bukti_follow", "bukti_follow_2",
                  "pilihan_1", "pilihan_2", "motivasi", "portofolio"]
        labels = {"pilihan_1": "Pilihan birdept 1", "pilihan_2": "Pilihan birdept 2",
                  "motivasi": "Motivasi join AM-FM", "portofolio": "Link portofolio (opsional)"}
        widgets = {"jenis_kelamin": forms.RadioSelect(), "motivasi": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["jenis_kelamin"].choices = Pendaftaran._meta.get_field("jenis_kelamin").choices
        for name in ("nama_lengkap", "npm", "jurusan"):
            self.fields[name].initial = profile.get_jurusan_display() if name == "jurusan" else getattr(profile, name)
            self.fields[name].widget.attrs.update({"class": "amfm-identity-input", "readonly": True})
        for name in ("pilihan_1", "pilihan_2"):
            self.fields[name].queryset = BirDep.objects.filter(is_active=True)
            self.fields[name].empty_label = "Pilih Birdept"
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "amfm-input")

    def clean_bukti_follow(self):
        return self._clean_bukti("bukti_follow")

    def clean_bukti_follow_2(self):
        return self._clean_bukti("bukti_follow_2")

    def _clean_bukti(self, name):
        file = self.cleaned_data.get(name)
        if not file:
            return file
        if file.size > 2 * 1024 * 1024:
            raise forms.ValidationError("Ukuran bukti follow maksimal 2 MB.")
        if file.image.format not in {"JPEG", "PNG"}:
            raise forms.ValidationError("Bukti follow harus berupa gambar JPG atau PNG.")
        # Gunakan ekstensi sesuai isi gambar, bukan nama berkas dari browser.
        file.name = "bukti.jpg" if file.image.format == "JPEG" else "bukti.png"
        return file

    def clean(self):
        data = super().clean()
        if not data.get("bukti_follow") and not data.get("bukti_follow_2") and not any(
            name in self.errors for name in ("bukti_follow", "bukti_follow_2")
        ):
            self.add_error("bukti_follow", "Unggah minimal satu gambar bukti follow Instagram.")
        if not any(self.portfolio_birdept(data.get(name)) for name in ("pilihan_1", "pilihan_2")):
            data["portofolio"] = ""
        return data

    @staticmethod
    def portfolio_birdept(birdept):
        return birdept is not None and (
            birdept.slug.casefold() in {"itf", "medkre"}
            or birdept.nama.casefold() in {"itf", "medkre"}
        )
