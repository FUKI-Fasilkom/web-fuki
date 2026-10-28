/* File tetap di input browser saat server mengembalikan error validasi. */
function amfmForm(initialStep, editMode) {
  return {
    step: initialStep, editMode, sending: false, review: [], portfolioVisible: false, motivationLength: 0,
    files: [null, null], errors: {}, requestError: '',
    init() {
      this.files = JSON.parse(document.getElementById('amfm-existing-files').textContent);
      this.updatePortfolio();
      const motivation = this.$refs.form.elements.motivasi;
      this.motivationLength = motivation.value.length;
      motivation.addEventListener('input', () => { this.motivationLength = motivation.value.length; });
    },
    fileInput(index) {
      return this.$refs.form.elements[index === 0 ? 'bukti_follow' : 'bukti_follow_2'];
    },
    updateFile(index) {
      if (this.files[index]?.url.startsWith('blob:')) URL.revokeObjectURL(this.files[index].url);
      const input = this.fileInput(index);
      const file = input.files[0];
      // Preview selalu bertipe gambar: berkas HTML/SVG tidak dieksekusi di origin situs.
      this.files[index] = file ? {
        name: file.name,
        url: URL.createObjectURL(new Blob([file], { type: file.type === 'image/jpeg' ? 'image/jpeg' : 'image/png' })),
      } : null;
      this.$refs.form.elements[`hapus_${input.name}`].value = '0';
      this.fileInput(0).setCustomValidity('');
      this.clearError(input.name);
      if (file) this.clearError('bukti_follow');
    },
    removeFile(index) {
      const input = this.fileInput(index);
      if (this.files[index]?.url.startsWith('blob:')) URL.revokeObjectURL(this.files[index].url);
      input.value = '';
      this.files[index] = null;
      this.$refs.form.elements[`hapus_${input.name}`].value = '1';
      this.fileInput(0).setCustomValidity('');
      this.clearError(input.name);
    },
    clearError(name) {
      delete this.errors[name];
    },
    updatePortfolio() {
      const ids = JSON.parse(document.getElementById('amfm-portfolio-ids').textContent);
      const fields = this.$refs.form.elements;
      this.portfolioVisible = ids.includes(fields.pilihan_1.value) || ids.includes(fields.pilihan_2.value);
      fields.portofolio.disabled = !this.portfolioVisible;
    },
    go(step) {
      this.step = step;
      this.$nextTick(() => this.$refs.form.querySelector(`[data-step="${step}"] h2`).focus());
    },
    valid(step) {
      if (step === 2) {
        const first = this.fileInput(0);
        first.setCustomValidity('');
        if (!this.files.some(Boolean)) {
          const message = 'Unggah minimal satu gambar bukti follow Instagram.';
          this.errors.bukti_follow = [message];
          first.setCustomValidity(message);
        }
      }
      const fields = this.$refs.form.querySelectorAll(`[data-step="${step}"] input, [data-step="${step}"] select, [data-step="${step}"] textarea`);
      const invalid = Array.from(fields).find(field => !field.checkValidity());
      if (invalid) {
        this.go(step);
        this.$nextTick(() => invalid.reportValidity());
        return false;
      }
      return true;
    },
    next() {
      if (!this.valid(this.step)) return;
      if (this.step === 2) this.buildReview();
      this.go(this.step + 1);
    },
    buildReview() {
      const fields = this.$refs.form.elements;
      const value = name => {
        const field = fields[name];
        if (field.tagName === 'SELECT') return field.selectedOptions[0]?.textContent || '—';
        if (name === 'jenis_kelamin') return field.value === 'L' ? 'Laki-laki' : 'Perempuan';
        return field.value || '—';
      };
      const rows = pairs => pairs.map(([name, label]) => ({ label, value: value(name) }));
      this.review = [
        { title: 'Data Diri', step: 1, rows: rows([['nama_lengkap', 'Nama Lengkap'], ['npm', 'NPM'], ['jurusan', 'Program Studi'], ['jenis_kelamin', 'Jenis Kelamin'], ['kontak', 'Kontak']]) },
        { title: 'Pilihan Birdept', step: 2, rows: [
          ...this.files.flatMap((file, index) => file ? [{ label: `Bukti Follow Instagram ${index + 1}`, value: file.name, href: file.url }] : []),
          ...rows([['pilihan_1', 'Birdept 1'], ['pilihan_2', 'Birdept 2'], ['motivasi', 'Motivasi'], ...(this.portfolioVisible ? [['portofolio', 'Portofolio']] : [])]),
        ] },
      ];
    },
    async submit(event) {
      event.preventDefault();
      if (this.sending) return;
      if (this.step !== 3) { this.next(); return; }
      if (!this.valid(1) || !this.valid(2)) return;
      this.sending = true;
      this.errors = {};
      this.requestError = '';
      try {
        const response = await fetch(this.$refs.form.action, {
          method: 'POST', body: new FormData(this.$refs.form),
          headers: { Accept: 'application/json' }, credentials: 'same-origin', redirect: 'error',
        });
        if (!response.headers.get('Content-Type')?.includes('application/json')) {
          throw new Error('unexpected-response');
        }
        const result = await response.json();
        if (result.redirect) { window.location.assign(result.redirect); return; }
        if (result.message) { this.requestError = result.message; return; }
        if (result.errors) {
          this.errors = Object.fromEntries(Object.entries(result.errors).map(([name, errors]) => [name, errors.map(error => error.message)]));
          this.go(result.step === 1 ? 1 : 2);
          return;
        }
        throw new Error('unexpected-response');
      } catch (_) {
        this.requestError = 'Pengiriman belum dapat dipastikan. File dan isianmu tetap di halaman ini. Coba kirim lagi; jika sesi berakhir, buka halaman pendaftaran di tab baru untuk masuk ulang.';
      } finally {
        this.sending = false;
      }
    },
  };
}
