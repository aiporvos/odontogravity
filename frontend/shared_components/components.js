/**
 * Shared UI Components - Modal, Toast, Helpers
 */
const UI = {
    // ── Modal ──────────────────────────────────────────
    showModal(title, bodyHtml, footerHtml = '') {
        document.getElementById('modal-title').textContent = title;
        document.getElementById('modal-body').innerHTML = bodyHtml;
        const footer = document.getElementById('modal-footer');
        footer.innerHTML = footerHtml;
        footer.classList.toggle('hidden', !footerHtml);
        document.getElementById('modal-overlay').classList.remove('hidden');
    },

    modal(html, title = 'Información') {
        this.showModal(title, html, '');
    },

    // `respuestaDelConfirm` solo importa cuando el modal abierto es un
    // UI.confirm(): es lo que se le devuelve a quien esta esperando la
    // respuesta. Cerrar sin elegir vale "no".
    closeModal(respuestaDelConfirm = false) {
        document.getElementById('modal-overlay').classList.add('hidden');
        document.getElementById('modal-body').innerHTML = '';
        document.getElementById('modal-footer').innerHTML = '';

        // Un confirm() cerrado con Escape, con la ×, clickeando el fondo o
        // navegando a otra pantalla dejaba su promesa colgada para siempre, y
        // el codigo que la esperaba no seguia nunca. Ahora siempre se resuelve.
        const pendiente = window._confirmResolve;
        window._confirmResolve = null;
        if (pendiente) pendiente(respuestaDelConfirm === true);
    },

    modalAbierto() {
        const overlay = document.getElementById('modal-overlay');
        return !!overlay && !overlay.classList.contains('hidden');
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
    confirm(title, message = '') {
        return new Promise((resolve) => {
            // Si no se pasa mensaje, no renderizamos el párrafo (evita mostrar "undefined").
            const body = message
                ? `<p style="color:var(--slate-600);font-size:.95rem;">${message}</p>`
                : '';
            const footer = `
                <button class="btn btn-secondary" onclick="UI.closeModal(false)">Cancelar</button>
                <button class="btn btn-danger" onclick="UI.closeModal(true)">Confirmar</button>
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

    // Un apellido con < o & no puede romper el HTML donde se lo dibuja.
    escape(txt) {
        return String(txt ?? '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
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
                } else if (input.type === 'number') {
                    data[input.name] = input.value === '' ? null : Number(input.value);
                } else {
                    data[input.name] = input.value;
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

// Escape cierra el modal. Es lo que espera cualquiera que haya usado una
// ventana modal antes, y hasta ahora la unica salida era apuntarle a la × o al
// borde. Un control de adentro que ya use Escape para lo suyo (el desplegable
// del buscador de pacientes, por ejemplo) frena el evento antes de que llegue
// hasta aca, asi que el primer Escape cierra la lista y el segundo el modal.
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && UI.modalAbierto()) UI.closeModal();
});
