/**
 * Agenda Page - Appointment management with timeline view
 */
Router.register('agenda', async (container) => {
    const today = UI.todayISO();
    let professionals = [];

    try {
        professionals = await API.getProfessionals();
    } catch (e) {}

    container.innerHTML = `
        <div class="page-header">
            <h1>Agenda de Turnos</h1>
            <div class="page-header-actions">
                <button class="btn btn-primary" id="btn-new-appointment">+ Nuevo Turno</button>
            </div>
        </div>

        <div class="card">
            <div class="agenda-filters">
                <input type="date" id="agenda-date" value="${today}">
                <select id="agenda-prof">
                    <option value="">Todos los profesionales</option>
                    ${professionals.map(p => `<option value="${p.id}">${p.full_name}</option>`).join('')}
                </select>
                <select id="agenda-location">
                    <option value="">Todas las sedes</option>
                    <option value="San Rafael">San Rafael</option>
                    <option value="Alvear">Alvear</option>
                </select>
                <select id="agenda-status">
                    <option value="">Todos los estados</option>
                    <option value="pending">Pendiente</option>
                    <option value="confirmed">Confirmado</option>
                    <option value="completed">Realizado</option>
                    <option value="cancelled">Cancelado</option>
                </select>
            </div>
            <div id="agenda-content" class="agenda-timeline"></div>
        </div>
    `;

    async function loadAgenda() {
        const date = document.getElementById('agenda-date').value;
        const profId = document.getElementById('agenda-prof').value;
        const location = document.getElementById('agenda-location').value;
        const status = document.getElementById('agenda-status').value;

        const content = document.getElementById('agenda-content');
        content.innerHTML = '<div class="loading-page"><div class="spinner"></div></div>';

        try {
            const appointments = await API.getAppointments({
                date_from: `${date}T00:00:00`,
                date_to: `${date}T23:59:59`,
                professional_id: profId,
                location: location,
                status: status,
            });

            if (appointments.length === 0) {
                content.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📅</div>
                        <div class="empty-state-text">No hay turnos para esta fecha</div>
                        <div class="empty-state-sub">Ajustá los filtros o creá un nuevo turno</div>
                    </div>`;
                return;
            }

            // Group by hour
            const byHour = {};
            appointments.forEach(a => {
                const hour = UI.formatTime(a.start_time);
                if (!byHour[hour]) byHour[hour] = [];
                byHour[hour].push(a);
            });

            content.innerHTML = Object.entries(byHour).map(([hour, appts]) => `
                <div class="agenda-slot">
                    <div class="slot-time">${hour}</div>
                    <div class="slot-cards">
                        ${appts.map(a => `
                            <div class="appointment-card status-${a.status}" onclick="AgendaPage.showAppointment('${a.id}')">
                                <div class="appt-name">${a.patient ? `${a.patient.last_name}, ${a.patient.first_name}` : 'Paciente'}</div>
                                <div class="appt-detail">
                                    ${a.professional ? a.professional.full_name : ''} · ${a.reason || 'Sin motivo'} · ${a.location || ''} 
                                    ${UI.statusBadge(a.status)}
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `).join('');
        } catch (err) {
            content.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error: ${err.message}</div></div>`;
        }
    }

    // Event listeners
    ['agenda-date', 'agenda-prof', 'agenda-location', 'agenda-status'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', loadAgenda);
    });

    document.getElementById('btn-new-appointment')?.addEventListener('click', () => AgendaPage.showNewAppointment(professionals));

    loadAgenda();
});


const AgendaPage = {
    async showAppointment(id) {
        try {
            const a = await API.getAppointment(id);
            const body = `
                <div class="form-grid">
                    <div class="form-group">
                        <label>Paciente</label>
                        <p style="font-weight:600">${a.patient ? `${a.patient.last_name}, ${a.patient.first_name}` : '-'}</p>
                    </div>
                    <div class="form-group">
                        <label>Profesional</label>
                        <p style="font-weight:600">${a.professional ? a.professional.full_name : '-'}</p>
                    </div>
                    <div class="form-group">
                        <label>Fecha/Hora</label>
                        <p>${UI.formatDateTime(a.start_time)}</p>
                    </div>
                    <div class="form-group">
                        <label>Duración</label>
                        <p>${a.duration_minutes} min</p>
                    </div>
                    <div class="form-group">
                        <label>Motivo</label>
                        <p>${a.reason || '-'}</p>
                    </div>
                    <div class="form-group">
                        <label>Estado</label>
                        <p>${UI.statusBadge(a.status)}</p>
                    </div>
                    <div class="form-group">
                        <label>Sede</label>
                        <p>${a.location || '-'}</p>
                    </div>
                    <div class="form-group">
                        <label>Canal</label>
                        <p>${UI.channelLabel(a.channel)}</p>
                    </div>
                    <div class="form-group form-group-full">
                        <label>Estado</label>
                        <select id="edit-appt-status" style="padding:.5rem;border:1px solid var(--slate-300);border-radius:var(--radius);">
                            <option value="pending" ${a.status==='pending'?'selected':''}>Pendiente</option>
                            <option value="confirmed" ${a.status==='confirmed'?'selected':''}>Confirmado</option>
                            <option value="completed" ${a.status==='completed'?'selected':''}>Realizado</option>
                            <option value="cancelled" ${a.status==='cancelled'?'selected':''}>Cancelado</option>
                            <option value="no_show" ${a.status==='no_show'?'selected':''}>No asistió</option>
                        </select>
                    </div>
                </div>
            `;
            const footer = `
                <button class="btn btn-danger btn-sm" onclick="AgendaPage.cancelAppointment('${a.id}')">Cancelar Turno</button>
                <button class="btn btn-primary btn-sm" onclick="AgendaPage.updateStatus('${a.id}')">Guardar Estado</button>
            `;
            UI.showModal('Detalle del Turno', body, footer);
        } catch (err) {
            UI.toast(err.message, 'error');
        }
    },

    async updateStatus(id) {
        const status = document.getElementById('edit-appt-status').value;
        try {
            await API.updateAppointment(id, { status });
            UI.closeModal();
            UI.toast('Estado actualizado', 'success');
            Router.navigate(null);
            Router.currentPage = null;
            Router.navigate('agenda');
        } catch (err) {
            UI.toast(err.message, 'error');
        }
    },

    async cancelAppointment(id) {
        const ok = await UI.confirm('Cancelar Turno', '¿Estás seguro de cancelar este turno?');
        if (ok) {
            try {
                await API.updateAppointment(id, { status: 'cancelled' });
                UI.toast('Turno cancelado', 'success');
                Router.currentPage = null;
                Router.navigate('agenda');
            } catch (err) {
                UI.toast(err.message, 'error');
            }
        }
    },

    async showNewAppointment(professionals = []) {
        let patients = [];
        try { patients = await API.getPatients(); } catch (e) {}
        if (!professionals.length) {
            try { professionals = await API.getProfessionals(); } catch (e) {}
        }

        const body = `
            <form id="form-new-appointment" class="form-grid">
                <div class="form-group">
                    <label>Paciente *</label>
                    <select name="patient_id" required>
                        <option value="">Seleccionar...</option>
                        ${patients.map(p => `<option value="${p.id}">${p.last_name}, ${p.first_name} (${p.dni})</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>Profesional *</label>
                    <select name="professional_id" required>
                        <option value="">Seleccionar...</option>
                        ${professionals.map(p => `<option value="${p.id}">${p.full_name}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>Fecha y Hora *</label>
                    <input type="datetime-local" name="start_time" required value="${UI.nowISO()}">
                </div>
                <div class="form-group">
                    <label>Duración (min)</label>
                    <input type="number" name="duration_minutes" value="30" min="15" step="15">
                </div>
                <div class="form-group">
                    <label>Sede</label>
                    <select name="location">
                        <option value="San Rafael">San Rafael</option>
                        <option value="Alvear">Alvear</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Estado</label>
                    <select name="status">
                        <option value="pending">Pendiente</option>
                        <option value="confirmed">Confirmado</option>
                    </select>
                </div>
                <div class="form-group form-group-full">
                    <label>Motivo</label>
                    <textarea name="reason" placeholder="Motivo de la consulta..."></textarea>
                </div>
                <div class="form-group form-group-full">
                    <label>Notas</label>
                    <textarea name="notes" placeholder="Notas adicionales..."></textarea>
                </div>
            </form>
        `;
        const footer = `
            <button class="btn btn-secondary" onclick="UI.closeModal()">Cancelar</button>
            <button class="btn btn-primary" onclick="AgendaPage.saveNewAppointment()">Guardar Turno</button>
        `;
        UI.showModal('Nuevo Turno', body, footer);
    },

    async saveNewAppointment() {
        const data = UI.getFormData('form-new-appointment');
        if (!data.patient_id || !data.professional_id || !data.start_time) {
            UI.toast('Completá los campos obligatorios', 'error');
            return;
        }
        data.duration_minutes = parseInt(data.duration_minutes) || 30;
        try {
            await API.createAppointment(data);
            UI.closeModal();
            UI.toast('Turno creado exitosamente', 'success');
            Router.currentPage = null;
            Router.navigate('agenda');
        } catch (err) {
            UI.toast(err.message, 'error');
        }
    },
};
