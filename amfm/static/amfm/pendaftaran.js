/* Satu form: berpindah langkah tidak menghapus file atau menyimpan identitas di browser storage. */
function amfmForm(initialStep) {
  return {
    step: initialStep, sending: false, review: [], portfolioVisible: false, motivationLength: 0,
    init() {
      this.updatePortfolio();
      const motivation = this.$refs.form.elements.motivasi;
      this.motivationLength = motivation.value.length;
      motivation.addEventListener('input', () => { this.motivationLength = motivation.value.length; });
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
        if (name === 'bukti_follow') return field.files[0]?.name || '—';
        if (name === 'jenis_kelamin') return field.value === 'L' ? 'Laki-laki' : 'Perempuan';
        return field.value || '—';
      };
      const rows = pairs => pairs.map(([name, label]) => ({ label, value: value(name) }));
      this.review = [
        { title: 'Data Diri', step: 1, rows: rows([['nama_lengkap', 'Nama Lengkap'], ['npm', 'NPM'], ['jurusan', 'Program Studi'], ['jenis_kelamin', 'Jenis Kelamin'], ['kontak', 'Kontak']]) },
        { title: 'Pilihan Birdept', step: 2, rows: rows([['bukti_follow', 'Bukti Follow Instagram'], ['pilihan_1', 'Birdept 1'], ['pilihan_2', 'Birdept 2'], ['motivasi', 'Motivasi'], ...(this.portfolioVisible ? [['portofolio', 'Portofolio']] : [])]) },
      ];
    },
    submit(event) {
      if (this.sending || this.step !== 3 || !this.valid(1) || !this.valid(2)) {
        event.preventDefault();
        if (this.step !== 3 && !this.sending) this.next();
        return;
      }
      this.sending = true;
    },
  };
}
