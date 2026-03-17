/**
 * API Service - HTTP client for Dental Studio Pro Backend
 */
const API = {
    BASE_URL: '/api',
    token: null,
    user: null,

    init() {
        const stored = localStorage.getItem('dsp_auth');
        if (stored) {
            const data = JSON.parse(stored);
            this.token = data.token;
            this.user = data.user;
        }
    },

    setAuth(token, user) {
        this.token = token;
        this.user = user;
        localStorage.setItem('dsp_auth', JSON.stringify({ token, user }));
    },

    clearAuth() {
        this.token = null;
        this.user = null;
        localStorage.removeItem('dsp_auth');
    },

    isAuthenticated() {
        return !!this.token;
    },

    headers() {
        const h = { 'Content-Type': 'application/json' };
        if (this.token) h['Authorization'] = `Bearer ${this.token}`;
        return h;
    },

    async request(method, path, body = null) {
        const opts = { method, headers: this.headers() };
        if (body && method !== 'GET') opts.body = JSON.stringify(body);

        const url = path.startsWith('/api') ? path : `${this.BASE_URL}${path}`;
        const res = await fetch(url, opts);

        if (res.status === 401) {
            this.clearAuth();
            window.location.reload();
            throw new Error('Sesión expirada');
        }

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `Error ${res.status}`);
        }

        return res.json();
    },

    get(path) { return this.request('GET', path); },
    post(path, body) { return this.request('POST', path, body); },
    put(path, body) { return this.request('PUT', path, body); },
    del(path) { return this.request('DELETE', path); },

    // ── Auth ──
    async login(email, password) {
        const formData = new URLSearchParams();
        formData.append('username', email);
        formData.append('password', password);

        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Error al iniciar sesión');
        }

        const data = await res.json();
        this.setAuth(data.access_token, data.user);
        return data;
    },

    // ── Clinic ──
    getPatients(q = '') { return this.get(`/clinic/patients${q ? `?q=${encodeURIComponent(q)}` : ''}`); },
    getPatient(id) { return this.get(`/clinic/patients/${id}`); },
    createPatient(data) { return this.post('/clinic/patients', data); },
    updatePatient(id, data) { return this.put(`/clinic/patients/${id}`, data); },
    deletePatient(id) { return this.del(`/clinic/patients/${id}`); },

    getAppointments(params = {}) {
        const q = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => { if (v) q.append(k, v); });
        return this.get(`/clinic/appointments?${q.toString()}`);
    },
    getAppointment(id) { return this.get(`/clinic/appointments/${id}`); },
    createAppointment(data) { return this.post('/clinic/appointments', data); },
    updateAppointment(id, data) { return this.put(`/clinic/appointments/${id}`, data); },
    deleteAppointment(id) { return this.del(`/clinic/appointments/${id}`); },

    getOdontogram(patientId) { return this.get(`/clinic/odontogram/${patientId}`); },
    createOdontogramEntry(data) { return this.post('/clinic/odontogram', data); },
    deleteOdontogramEntry(id) { return this.del(`/clinic/odontogram/${id}`); },

    getProfessionals() { return this.get('/clinic/professionals'); },
    search(q) { return this.get(`/clinic/search?q=${encodeURIComponent(q)}`); },

    // ── Admin ──
    getUsers() { return this.get('/admin/users'); },
    createUser(data) { return this.post('/admin/users', data); },
    updateUser(id, data) { return this.put(`/admin/users/${id}`, data); },
    deleteUser(id) { return this.del(`/admin/users/${id}`); },

    getAdminProfessionals() { return this.get('/admin/professionals'); },
    createProfessional(data) { return this.post('/admin/professionals', data); },
    updateProfessional(id, data) { return this.put(`/admin/professionals/${id}`, data); },
    deleteProfessional(id) { return this.del(`/admin/professionals/${id}`); },

    getLocations() { return this.get('/admin/locations'); },
    getInsurances() { return this.get('/admin/insurances'); },
};

API.init();
