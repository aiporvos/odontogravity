/**
 * Agenda Page - Appointment management with timeline, week and month views
 */
Router.register('agenda', async (container) => {
    const today = UI.todayISO();
    let professionals = [];
    let state = {
        view: 'day', // 'day', 'week', 'month'
        currentDate: today
    };

    try {
        professionals = await API.getProfessionals();
    } catch (e) {}

    container.innerHTML = `
        <div class="page-header">
            <h1>Agenda de Turnos</h1>
            <div class="page-header-actions">
                <div class="btn-group" style="margin-right:1rem">
                    <button class="btn btn-ghost btn-sm active" data-view="day">Día</button>
                    <button class="btn btn-ghost btn-sm" data-view="week">Semana</button>
                    <button class="btn btn-ghost btn-sm" data-view="month">Mes</button>
                </div>
                <button class="btn btn-primary" id="btn-new-appointment">+ Nuevo Turno</button>
            </div>
        </div>

        <div class="card">
            <div class="agenda-filters">
                <div class="nav-arrows" style="display:flex; align-items:center; gap:.5rem; margin-right:1rem;">
                    <button class="btn btn-icon btn-sm" id="cal-prev">‹</button>
                    <button class="btn btn-icon btn-sm" id="cal-next">›</button>
                    <button class="btn btn-ghost btn-sm" id="cal-today">Hoy</button>
                </div>
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
            <div id="agenda-header-info" style="margin-bottom: 1.5rem; font-weight: 700; color: var(--slate-700); text-transform: capitalize; font-size: 1.1rem;"></div>
            <div id="agenda-content" class="agenda-timeline"></div>
        </div>
    `;

    async function loadAgenda() {
        const date = state.currentDate;
        const profId = document.getElementById('agenda-prof').value;
        const location = document.getElementById('agenda-location').value;
        const status = document.getElementById('agenda-status').value;

        const d = new Date(date + 'T12:00:00');
        const headerInfo = document.getElementById('agenda-header-info');
        
        let headerText = '';
        if (state.view === 'day') {
            headerText = d.toLocaleDateString('es-AR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
        } else if (state.view === 'week') {
            const start = new Date(d);
            start.setDate(d.getDate() - d.getDay());
            const end = new Date(start);
            end.setDate(start.getDate() + 6);
            headerText = `Del ${start.getDate()} al ${end.getDate()} de ${end.toLocaleDateString('es-AR', {month:'long', year:'numeric'})}`;
        } else {
            headerText = d.toLocaleDateString('es-AR', { month: 'long', year: 'numeric' });
        }
        headerInfo.textContent = headerText;

        const content = document.getElementById('agenda-content');
        content.innerHTML = '<div class="loading-page"><div class="spinner"></div></div>';

        try {
            let dateFrom, dateTo;
            if (state.view === 'day') {
                dateFrom = `${date}T00:00:00`;
                dateTo = `${date}T23:59:59`;
            } else if (state.view === 'week') {
                const start = new Date(d);
                start.setDate(d.getDate() - d.getDay());
                const end = new Date(start);
                end.setDate(start.getDate() + 6);
                dateFrom = `${start.toISOString().split('T')[0]}T00:00:00`;
                dateTo = `${end.toISOString().split('T')[0]}T23:59:59`;
            } else {
                const start = new Date(d.getFullYear(), d.getMonth(), 1);
                const end = new Date(d.getFullYear(), d.getMonth() + 1, 0);
                dateFrom = `${start.toISOString().split('T')[0]}T00:00:00`;
                dateTo = `${end.toISOString().split('T')[0]}T23:59:59`;
            }

            const appointments = await API.getAppointments({
                date_from: dateFrom,
                date_to: dateTo,
                professional_id: profId,
                location: location,
                status: status,
            });

            if (state.view === 'day') {
                if (appointments.length === 0) {
                    content.innerHTML = `<div class="empty-state"><div class="empty-state-text">No hay turnos hoy</div></div>`;
                    return;
                }
                const byHour = {};
                appointments.sort((a,b) => new Date(a.start_time) - new Date(b.start_time)).forEach(a => {
                    const hour = UI.formatTime(a.start_time);
                    if (!byHour[hour]) byHour[hour] = [];
                    byHour[hour].push(a);
                });
                content.innerHTML = Object.entries(byHour).map(([hour, appts]) => `
                    <div class="agenda-slot">
                        <div class="slot-time">${hour}</div>
                        <div class="slot-cards">
                            ${appts.map(a => {
                                const icons = { pending:'⏳', confirmed:'✅', completed:'🏁', cancelled:'❌', no_show:'🚫' };
                                return `
                                    <div class="appointment-card status-${a.status}" onclick="AgendaPage.showAppointment('${a.id}')">
                                        <div class="appt-name">
                                            <span>${icons[a.status] || ''}</span>
                                            ${a.patient ? `${a.patient.last_name}, ${a.patient.first_name}` : 'Paciente'}
                                        </div>
                                        <div class="appt-detail">${a.professional ? a.professional.full_name : ''} · ${a.reason || ''}</div>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    </div>
                `).join('');
            } else if (state.view === 'week') {
                const days = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
                const startDate = new Date(dateFrom.split('T')[0] + 'T12:00:00');
                let html = '<div class="calendar-grid-week">';
                for (let i = 0; i < 7; i++) {
                    const current = new Date(startDate);
                    current.setDate(startDate.getDate() + i);
                    const iso = current.toISOString().split('T')[0];
                    const dayAppts = appointments.filter(a => a.start_time.startsWith(iso));
                    html += `
                        <div class="calendar-day-cell">
                            <div class="calendar-day-header ${iso === today ? 'current-day' : ''}">${days[i]} ${current.getDate()}</div>
                            ${dayAppts.map(a => {
                                const icons = { pending:'⏳', confirmed:'✅', completed:'🏁', cancelled:'❌', no_show:'🚫' };
                                return `
                                    <div class="mini-appt status-${a.status}" onclick="AgendaPage.showAppointment('${a.id}')">
                                        <span>${icons[a.status] || ''}</span>
                                        ${UI.formatTime(a.start_time)} ${a.patient ? a.patient.last_name : ''}
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    `;
                }
                html += '</div>';
                content.innerHTML = html;
            } else {
                const startDate = new Date(dateFrom.split('T')[0] + 'T12:00:00');
                const endDate = new Date(dateTo.split('T')[0] + 'T12:00:00');
                let html = '<div class="calendar-grid-week">';
                const firstDay = startDate.getDay();
                for (let i = 0; i < firstDay; i++) html += '<div class="calendar-day-cell" style="background:var(--slate-50)"></div>';
                for (let d = 1; d <= endDate.getDate(); d++) {
                    const current = new Date(startDate.getFullYear(), startDate.getMonth(), d, 12, 0, 0);
                    const iso = current.toISOString().split('T')[0];
                    const dayAppts = appointments.filter(a => a.start_time.startsWith(iso));
                    html += `
                        <div class="calendar-day-cell">
                            <div class="calendar-day-header ${iso === today ? 'current-day' : ''}">${d}</div>
                            ${dayAppts.slice(0, 4).map(a => {
                                const icons = { pending:'⏳', confirmed:'✅', completed:'🏁', cancelled:'❌', no_show:'🚫' };
                                return `
                                    <div class="mini-appt status-${a.status}" onclick="AgendaPage.showAppointment('${a.id}')">
                                        <span>${icons[a.status] || ''}</span>
                                        ${a.patient ? a.patient.last_name : '...'}
                                    </div>
                                `;
                            }).join('')}
                            ${dayAppts.length > 4 ? `<div style="font-size:.6rem;color:var(--slate-400)">+ ${dayAppts.length - 4} más</div>` : ''}
                        </div>
                    `;
                }
                html += '</div>';
                content.innerHTML = html;
            }
        } catch (err) {
            content.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error: ${err.message}</div></div>`;
        }
    }

    document.querySelectorAll('.btn-group .btn').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.btn-group .btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.view = btn.dataset.view;
            loadAgenda();
        };
    });

    document.getElementById('cal-today').onclick = () => {
        state.currentDate = today;
        document.getElementById('agenda-date').value = today;
        loadAgenda();
    };

    document.getElementById('cal-prev').onclick = () => {
        const d = new Date(state.currentDate + 'T12:00:00');
        if (state.view === 'day') d.setDate(d.getDate() - 1);
        else if (state.view === 'week') d.setDate(d.getDate() - 7);
        else d.setMonth(d.getMonth() - 1);
        state.currentDate = d.toISOString().split('T')[0];
        document.getElementById('agenda-date').value = state.currentDate;
        loadAgenda();
    };

    document.getElementById('cal-next').onclick = () => {
        const d = new Date(state.currentDate + 'T12:00:00');
        if (state.view === 'day') d.setDate(d.getDate() + 1);
        else if (state.view === 'week') d.setDate(d.getDate() + 7);
        else d.setMonth(d.getMonth() + 1);
        state.currentDate = d.toISOString().split('T')[0];
        document.getElementById('agenda-date').value = state.currentDate;
        loadAgenda();
    };

    ['agenda-date', 'agenda-prof', 'agenda-location', 'agenda-status'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', (e) => {
            if (id === 'agenda-date') state.currentDate = e.target.value;
            loadAgenda();
        });
    });

    const btnNew = document.getElementById('btn-new-appointment');
    if (btnNew) btnNew.onclick = () => AgendaPage.showNewAppointment(professionals);

    // Exponer la función para recargar desde fuera
    AgendaPage.loadAgenda = loadAgenda;

    loadAgenda();
});

const AgendaPage = {
    async showAppointment(id) {
        try {
            const a = await API.getAppointment(id);
            UI.showModal('Detalle del Turno', `
                <div class="form-grid">
                    <div class="form-group"><label>Paciente</label><p><strong>${a.patient ? `${a.patient.last_name}, ${a.patient.first_name}` : '-'}</strong></p></div>
                    <div class="form-group"><label>Profesional</label><p>${a.professional ? a.professional.full_name : '-'}</p></div>
                    <div class="form-group"><label>Fecha/Hora</label><p>${UI.formatDateTime(a.start_time)}</p></div>
                    <div class="form-group"><label>Motivo</label><p>${a.reason || '-'}</p></div>
                    <div class="form-group">
                        <label>Estado</label>
                        <select id="update-appt-status" class="form-control" style="margin-top:.5rem;">
                            <option value="pending" ${a.status==='pending'?'selected':''}>⏳ Pendiente</option>
                            <option value="confirmed" ${a.status==='confirmed'?'selected':''}>✅ Confirmado</option>
                            <option value="completed" ${a.status==='completed'?'selected':''}>🏁 Realizado</option>
                            <option value="cancelled" ${a.status==='cancelled'?'selected':''}>❌ Cancelado</option>
                            <option value="no_show" ${a.status==='no_show'?'selected':''}>🚫 No asistió</option>
                        </select>
                    </div>
                </div>
            `, `
                <button class="btn btn-secondary" onclick="UI.closeModal()">Cerrar</button>
                <button class="btn btn-primary" onclick="AgendaPage.updateStatus('${a.id}')">Actualizar Estado</button>
            `);
        } catch (err) { UI.toast(err.message, 'error'); }
    },

    async updateStatus(id) {
        const newStatus = document.getElementById('update-appt-status').value;
        try {
            await API.updateAppointment(id, { status: newStatus });
            UI.toast('Estado actualizado', 'success');
            UI.closeModal();
            if (AgendaPage.loadAgenda) AgendaPage.loadAgenda();
        } catch (err) { UI.toast(err.message, 'error'); }
    },

    async showNewAppointment(professionals = []) {
        let patients = [];
        try { patients = await API.getPatients(); } catch (e) {}
        UI.showModal('Nuevo Turno', `
            <form id="form-new-appointment" class="form-grid">
                <div class="form-group">
                    <label>Paciente *</label>
                    <select name="patient_id" required>
                        <option value="">Seleccionar...</option>
                        ${patients.map(p => `<option value="${p.id}">${p.last_name}, ${p.first_name}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>Profesional *</label>
                    <select name="professional_id" required>
                        ${professionals.map(p => `<option value="${p.id}">${p.full_name}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>Fecha y Hora *</label>
                    <input type="datetime-local" name="start_time" required value="${UI.nowISO()}">
                </div>
                <div class="form-group form-group-full">
                    <label>Motivo</label>
                    <textarea name="reason"></textarea>
                </div>
            </form>
        `, `
            <button class="btn btn-secondary" onclick="UI.closeModal()">Cancelar</button>
            <button class="btn btn-primary" onclick="AgendaPage.saveNewAppointment()">Guardar</button>
        `);
    },

    async saveNewAppointment() {
        const data = UI.getFormData('form-new-appointment');
        try {
            await API.createAppointment(data);
            UI.closeModal();
            UI.toast('Turno creado', 'success');
            if (AgendaPage.loadAgenda) AgendaPage.loadAgenda();
        } catch (err) { UI.toast(err.message, 'error'); }
    }
};
