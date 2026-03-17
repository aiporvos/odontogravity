/**
 * Shared UI Components - Modal, Toast, Helpers
 */
const UI = {
    // ── Modal ──────────────────────────────────────────
    showModal(title, bodyHtml, footerHtml = '') {
        document.getElementById('modal-title').textContent = title;
        document.getElementById('modal-body').innerHTML = bodyHtml;
        document.getElementById('modal-footer').innerHTML = footerHtml;
        document.getElementById('modal-overlay').classList.remove('hidden');
    },

    closeModal() {
        document.getElementById('modal-overlay').classList.add('hidden');
    },

    // ── Toast ──────────────────────────────────────────
    toast(message, type = 'info') {
        const icons = { success: '✅', error: '❌', info: 'ℹ️' };
        const container = document.getElementById('toast-container');
        const el = document.createElement('div');
        el.className = `toast toast-${type}`;
        el.innerHTML = `<span>${icons[type] || ''}</span><span>${message}</span>`;
        container.appendChild(el);
        setTimeout(() => el.remove(), 4000);
    },

    // ── Confirm ────────────────────────────────────────
    confirm(title, message) {
        return new Promise((resolve) => {
            const body = `<p style="color:var(--slate-600);font-size:.95rem;">${message}</p>`;
            const footer = `
                <button class="btn btn-secondary" onclick="UI.closeModal(); window._confirmResolve(false)">Cancelar</button>
                <button class="btn btn-danger" onclick="UI.closeModal(); window._confirmResolve(true)">Confirmar</button>
            `;
            window._confirmResolve = resolve;
            this.showModal(title, body, footer);
        });
    },

    // ── Format Helpers ─────────────────────────────────
    formatDate(dateStr) {
        if (!dateStr) return '-';
        const d = new Date(dateStr);
        return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
    },

    formatTime(dateStr) {
        if (!dateStr) return '-';
        const d = new Date(dateStr);
        return d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
    },

    formatDateTime(dateStr) {
        if (!dateStr) return '-';
        return `${this.formatDate(dateStr)} ${this.formatTime(dateStr)}`;
    },

    statusBadge(status) {
        const labels = {
            pending: 'Pendiente', confirmed: 'Confirmado',
            completed: 'Realizado', cancelled: 'Cancelado', no_show: 'No asistió',
        };
        return `<span class="badge badge-${status}">${labels[status] || status}</span>`;
    },

    channelLabel(channel) {
        const labels = {
            web: '🌐 Web', bot_whatsapp: '📱 WhatsApp',
            bot_telegram: '💬 Telegram', phone: '📞 Teléfono',
        };
        return labels[channel] || channel;
    },

    // ── Form Helpers ───────────────────────────────────
    getFormData(formId) {
        const form = document.getElementById(formId);
        if (!form) return {};
        const data = {};
        const inputs = form.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
            if (input.name) {
                if (input.type === 'checkbox') {
                    data[input.name] = input.checked;
                } else {
                    data[input.name] = input.value || null;
                }
            }
        });
        return data;
    },

    // ── Date ──
    todayISO() {
        return new Date().toISOString().split('T')[0];
    },

    nowISO() {
        const d = new Date();
        d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
        return d.toISOString().slice(0, 16);
    },
};

// Close modal listeners
document.getElementById('modal-close')?.addEventListener('click', () => UI.closeModal());
document.getElementById('modal-overlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'modal-overlay') UI.closeModal();
});
