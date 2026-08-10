/**
 * API Service - HTTP client for Silprodent Backend
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
        const opts = { method, headers: this.headers(), cache: 'no-store' };
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
            throw new Error(this.errorMessage(errData, res.status));
        }

        return res.json();
    },

    // En un error de validacion (422) FastAPI manda "detail" como una lista de
    // objetos; al pasarla a Error() se veia "[object Object]" en el toast.
    errorMessage(errData, status) {
        const detail = errData && errData.detail;
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail) && detail.length) {
            return detail
                .map(d => {
                    const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : null;
                    return field ? `${field}: ${d.msg}` : d.msg;
                })
                .filter(Boolean)
                .join(' · ');
        }
        return `Error ${status}`;
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
    createOdontogramEntriesBulk(data) { return this.post('/clinic/odontogram/bulk', data); },
    updateOdontogramEntry(id, data) { return this.put(`/clinic/odontogram/${id}`, data); },
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
    createLocation(data) { return this.post('/admin/locations', data); },
    deleteLocation(id) { return this.del(`/admin/locations/${id}`); },

    getInsurances() { return this.get('/clinic/insurances'); },
    createInsurance(data) { return this.post('/clinic/insurances', data); },
    updateInsurance(id, data) { return this.put(`/clinic/insurances/${id}`, data); },
    deleteInsurance(id) { return this.del(`/clinic/insurances/${id}`); },

    getConfigs() { return this.get('/admin/configs'); },
    setConfig(key, value, description = '') { return this.post('/admin/configs', { key, value, description }); },
    // Subconjunto no sensible editable por el personal de clínica (recepción)
    getBotSettings() { return this.get('/clinic/bot-settings'); },
    setBotSettings(data) { return this.post('/clinic/bot-settings', data); },

    // Horarios y ausencias
    getSchedule() { return this.get('/clinic/schedule'); },
    saveSchedule(blocks) { return this.put('/clinic/schedule', blocks); },
    getTimeOff() { return this.get('/clinic/time-off'); },
    createTimeOff(data) { return this.post('/clinic/time-off', data); },
    deleteTimeOff(id) { return this.del(`/clinic/time-off/${id}`); },
    getRescheduleList() { return this.get('/clinic/reschedule-list'); },

    // Feriados
    getHolidays() { return this.get('/clinic/holidays'); },
    createHoliday(data) { return this.post('/clinic/holidays', data); },
    deleteHoliday(id) { return this.del(`/clinic/holidays/${id}`); },
};

API.init();
