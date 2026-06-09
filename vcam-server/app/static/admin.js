// IP LIVE — admin SPA controller.
//
// Single Alpine.js component. Each tab in the side rail is just a
// CSS toggle on `page`; data loads lazily the first time you switch
// to a tab and refreshes on a manual reload (no auto-poll, to keep
// the server quiet — admin actions are bursty, not live).

function adminApp() {
  return {
    // ── nav ─────────────────────────────────────────────
    page: 'dashboard',
    nav: [
      { id: 'dashboard', label: 'ภาพรวม',          icon: '📊' },
      { id: 'customers', label: 'ลูกค้า',          icon: '👤' },
      { id: 'licenses',  label: 'License Keys',    icon: '🔑' },
      { id: 'payments',  label: 'การชำระเงิน',     icon: '💳' },
      { id: 'support',   label: 'Support Inbox',   icon: '🛟' },
      { id: 'admins',    label: 'แอดมิน',          icon: '👥' },
    ],

    // ── dashboard state ────────────────────────────────
    kpis: [
      { label: 'ลูกค้าทั้งหมด',     value: '—', hint: 'ข้อมูลล่าสุด' },
      { label: 'License ใช้งานอยู่', value: '—', hint: 'ไม่รวม revoked' },
      { label: 'Activations',        value: '—', hint: 'จำนวน PC ที่ใช้งาน' },
      { label: 'Support เปิดอยู่',   value: '—', hint: 'ยังไม่ปิด' },
    ],
    recentActivations: [],

    // ── customers ───────────────────────────────────────
    search: '',
    customers: [],
    showNewCustomer: false,
    newCustomer: { name: '', line_id: '', phone: '', notes: '' },

    // ── licenses ────────────────────────────────────────
    licStatus: '',
    licenses: [],
    showIssueLicense: false,
    issuingLicense: false,
    issueForm: {
      customer_id: '',
      customer_name: '',
      max_devices: 3,
      days: 30,
      expiry: '',
      note: '',
    },
    lastIssuedKey: null,

    // ── payments ────────────────────────────────────────
    payments: [],

    // ── support ─────────────────────────────────────────
    tickets: [],

    // ── admins ──────────────────────────────────────────
    admins: [],
    showNewAdmin: false,
    creatingAdmin: false,
    newAdmin: { email: '', password: '', display_name: '' },

    // ── lifecycle ───────────────────────────────────────
    init() {
      this.loadDashboard();
      // Whenever the user switches tab, kick off the right loader.
      // We watch via $watch so loaders run only on tab change, not
      // on every keystroke / hover.
      this.$watch('page', (p) => {
        if (p === 'dashboard') this.loadDashboard();
        if (p === 'customers') this.loadCustomers();
        if (p === 'licenses')  this.loadLicenses();
        if (p === 'payments')  this.loadPayments();
        if (p === 'support')   this.loadTickets();
        if (p === 'admins')    this.loadAdmins();
      });
    },

    // ── HTTP helper ─────────────────────────────────────
    async api(method, url, body) {
      const opts = {
        method,
        headers: { 'content-type': 'application/json' },
        credentials: 'same-origin',
      };
      if (body !== undefined) opts.body = JSON.stringify(body);
      const resp = await fetch(url, opts);
      if (resp.status === 401) {
        // Cookie expired or admin deactivated. Bounce to login.
        window.location.href = '/admin/login';
        return null;
      }
      if (!resp.ok) {
        const text = await resp.text();
        alert(`Error ${resp.status}: ${text}`);
        return null;
      }
      return resp.json();
    },

    // ── dashboard ───────────────────────────────────────
    async loadDashboard() {
      // Parallel fetch — three small endpoints, < 100 ms total.
      const [customers, licenses, tickets] = await Promise.all([
        this.api('GET', '/api/admin/customers'),
        this.api('GET', '/api/admin/licenses'),
        this.api('GET', '/api/admin/support'),
      ]);
      if (!customers || !licenses || !tickets) return;

      const activeLic   = licenses.filter(l => l.status === 'active').length;
      const openTickets = tickets.filter(t => t.status === 'open').length;

      // Activations: we don't have a dedicated endpoint yet — derive
      // from licenses' attached activations on the customer detail.
      // For the dashboard, count via an extra (cheap) nested API
      // call.
      let actCount = 0;
      let recent = [];
      for (const c of customers.slice(0, 20)) {
        const detail = await this.api('GET', `/api/admin/customers/${c.id}`);
        if (!detail) continue;
        actCount += detail.activations.length;
        recent = recent.concat(detail.activations);
      }
      recent.sort((a, b) => (a.last_seen_at < b.last_seen_at ? 1 : -1));
      this.recentActivations = recent.slice(0, 10);

      this.kpis = [
        { label: 'ลูกค้าทั้งหมด',     value: customers.length, hint: 'รวม inactive' },
        { label: 'License ใช้งานอยู่', value: activeLic,        hint: 'ไม่รวม revoked' },
        { label: 'Activations',        value: actCount,          hint: 'จำนวน PC ที่ใช้งาน' },
        { label: 'Support เปิดอยู่',   value: openTickets,       hint: 'ยังไม่ปิด' },
      ];
    },

    // ── customers ───────────────────────────────────────
    async loadCustomers() {
      const q = encodeURIComponent(this.search || '');
      const rows = await this.api('GET', `/api/admin/customers?q=${q}`);
      if (rows) this.customers = rows;
    },
    async createCustomer() {
      if (!this.newCustomer.name.trim()) {
        alert('ใส่ชื่อก่อน');
        return;
      }
      const created = await this.api('POST', '/api/admin/customers', this.newCustomer);
      if (!created) return;
      this.showNewCustomer = false;
      this.newCustomer = { name: '', line_id: '', phone: '', notes: '' };
      this.loadCustomers();
    },
    openCustomer(id) {
      // Phase 2: open detail drawer. For now, list licenses for
      // the customer so the operator can issue a key from CLI
      // until the modal lands.
      window.open(`/api/admin/customers/${id}`, '_blank');
    },

    // ── licenses ────────────────────────────────────────
    async loadLicenses() {
      const s = this.licStatus ? `?status=${encodeURIComponent(this.licStatus)}` : '';
      const rows = await this.api('GET', `/api/admin/licenses${s}`);
      if (rows) this.licenses = rows;
    },
    async openIssueLicense(customerId = '') {
      if (this.customers.length === 0) {
        await this.loadCustomers();
      }
      this.issueForm = {
        customer_id: customerId || '',
        customer_name: '',
        max_devices: 3,
        days: 30,
        expiry: '',
        note: '',
      };
      this.showIssueLicense = true;
    },
    async issueLicense() {
      const cid = Number(this.issueForm.customer_id);
      if (!cid) {
        alert('เลือกลูกค้าก่อน');
        return;
      }
      const maxDevices = Number(this.issueForm.max_devices || 3);
      const days = Number(this.issueForm.days || 30);
      if (maxDevices < 1) {
        alert('จำนวนมือถือต้องมากกว่า 0');
        return;
      }
      if (!this.issueForm.expiry && days < 1) {
        alert('จำนวนวันต้องมากกว่า 0 หรือใส่วันหมดอายุ');
        return;
      }
      const payload = {
        max_devices: maxDevices,
        days,
        expiry: this.issueForm.expiry || '',
        customer_name: (this.issueForm.customer_name || '').trim(),
        note: (this.issueForm.note || '').trim(),
      };
      this.issuingLicense = true;
      try {
        const issued = await this.api(
          'POST',
          `/api/admin/customers/${cid}/licenses`,
          payload,
        );
        if (!issued) return;
        this.lastIssuedKey = issued;
        this.showIssueLicense = false;
        await this.loadLicenses();
        await this.loadDashboard();
      } finally {
        this.issuingLicense = false;
      }
    },
    async copyIssuedKey() {
      if (!this.lastIssuedKey) return;
      const text = this.lastIssuedKey.key;
      try {
        await navigator.clipboard.writeText(text);
        alert('ก๊อป License Key แล้ว');
      } catch (e) {
        window.prompt('ก๊อป License Key:', text);
      }
    },

    // ── payments ────────────────────────────────────────
    async loadPayments() {
      const rows = await this.api('GET', '/api/admin/payments');
      if (rows) this.payments = rows;
    },

    // ── support ─────────────────────────────────────────
    async loadTickets() {
      const rows = await this.api('GET', '/api/admin/support');
      if (rows) this.tickets = rows;
    },

    // ── admins ──────────────────────────────────────────
    async loadAdmins() {
      const rows = await this.api('GET', '/api/admin/admins');
      if (rows) this.admins = rows;
    },
    async createAdmin() {
      const email = (this.newAdmin.email || '').trim();
      const password = this.newAdmin.password || '';
      if (!email) {
        alert('ใส่อีเมลแอดมินก่อน');
        return;
      }
      if (password.length < 6) {
        alert('รหัสผ่านต้องอย่างน้อย 6 ตัวอักษร');
        return;
      }
      this.creatingAdmin = true;
      try {
        const created = await this.api('POST', '/api/admin/admins', {
          email,
          password,
          display_name: (this.newAdmin.display_name || '').trim(),
        });
        if (!created) return;
        this.showNewAdmin = false;
        this.newAdmin = { email: '', password: '', display_name: '' };
        await this.loadAdmins();
        alert('เพิ่มแอดมินเรียบร้อย');
      } finally {
        this.creatingAdmin = false;
      }
    },
  };
}
