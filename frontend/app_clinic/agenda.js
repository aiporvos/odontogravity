/**
 * Agenda Page - Appointment management with timeline, week and month views
 */
Router.register('agenda', async (container) => {
    const today = UI.todayISO();
    let professionals = [];
    let state = {
        view: 'week', // 'day', 'week', 'month'
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
                    <button class="btn btn-ghost btn-sm" data-view="day">Día</button>
                    <button class="btn btn-ghost btn-sm active" data-view="week">Semana</button>
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
                <select id="agenda-grouping">
                    <option value="chronological">Orden Cronológico</option>
                    <option value="priority">Agrupado por Prioridad</option>
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

            // Conflict Detection (same professional, overlapping times, active status)
            const conflictIds = new Set();
            const activeAppts = appointments.filter(a => a.status !== 'cancelled');
            for (let i = 0; i < activeAppts.length; i++) {
                const a = activeAppts[i];
                const aStart = new Date(a.start_time).getTime();
                const aEnd = aStart + (a.duration_minutes || 30) * 60 * 1000;
                for (let j = i + 1; j < activeAppts.length; j++) {
                    const b = activeAppts[j];
                    if (a.professional_id === b.professional_id) {
                        const bStart = new Date(b.start_time).getTime();
                        const bEnd = bStart + (b.duration_minutes || 30) * 60 * 1000;
                        if (aStart < bEnd && bStart < aEnd) {
                            conflictIds.add(a.id);
                            conflictIds.add(b.id);
                        }
                    }
                }
            }

            const grouping = document.getElementById('agenda-grouping')?.value || 'chronological';

            if (state.view === 'day') {
                if (appointments.length === 0) {
                    content.innerHTML = `<div class="empty-state"><div class="empty-state-text">No hay turnos hoy</div></div>`;
                    return;
                }

                // Show conflict banner if there are conflicts
                let bannerHtml = '';
                if (conflictIds.size > 0) {
                    bannerHtml = `
                        <div class="card" style="background:var(--danger-light); border-color:var(--danger); margin-bottom:1.5rem; padding: 1rem;">
                            <div style="display:flex; gap:1rem; align-items:center;">
                                <div style="font-size:1.5rem;">⚠️</div>
                                <div style="font-size:.9rem; color:var(--danger-dark); font-weight: 600;">
                                    Conflicto de Agenda: Se han detectado turnos superpuestos para el mismo profesional.
                                </div>
                            </div>
                        </div>
                    `;
                }

                // Render card function helper
                const renderCard = (a) => {
                    const icons = { pending:'⏳', confirmed:'✅', completed:'🏁', cancelled:'❌', no_show:'🚫' };
                    const hasConflict = conflictIds.has(a.id);
                    const pri = a.treatment_priority || 'Baja';
                    const priorityClass = pri === 'Alta' ? 'badge-cancelled' : (pri === 'Media' ? 'badge-pending' : 'badge-confirmed');
                    
                    const conflictBadge = hasConflict ? `
                        <span class="badge badge-cancelled" style="font-weight:700; display:inline-flex; align-items:center; gap:0.25rem;">
                            ⚠️ ¡Superposición!
                        </span>
                    ` : '';

                    return `
                        <div class="appointment-card status-${a.status}" 
                             onclick="AgendaPage.showAppointment('${a.id}')"
                             style="${hasConflict ? 'border-left-color: var(--danger); outline: 2px solid var(--danger);' : ''}">
                            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:.5rem;">
                                <div class="appt-name" style="display:flex; align-items:center; gap:.5rem;">
                                    <span>${icons[a.status] || ''}</span>
                                    ${a.patient ? `${a.patient.last_name}, ${a.patient.first_name}` : 'Paciente'}
                                </div>
                                <div style="display:flex; gap:.35rem; align-items:center;">
                                    ${conflictBadge}
                                    <span class="badge ${priorityClass}" style="font-size:.7rem; font-weight:700;">
                                        Prioridad: ${pri}
                                    </span>
                                </div>
                            </div>
                            <div class="appt-detail" style="margin-top:.25rem;">
                                <strong>${UI.formatTime(a.start_time)}</strong> · 
                                ${a.professional ? a.professional.full_name : ''} · 
                                ${a.reason || ''}
                            </div>
                        </div>
                    `;
                };

                if (grouping === 'priority') {
                    // Group by priority
                    const groups = {
                        'Alta': [],
                        'Media': [],
                        'Baja': []
                    };
                    appointments.forEach(a => {
                        const pri = a.treatment_priority || 'Baja';
                        const key = pri === 'Alta' ? 'Alta' : (pri === 'Media' ? 'Media' : 'Baja');
                        groups[key].push(a);
                    });

                    // Sort each group chronologically
                    Object.values(groups).forEach(g => {
                        g.sort((a, b) => new Date(a.start_time) - new Date(b.start_time));
                    });

                    const groupConfig = [
                        { name: 'Alta Prioridad', key: 'Alta', color: 'var(--danger)', bg: 'var(--danger-light)', text: 'var(--danger-dark)', icon: '🔴' },
                        { name: 'Media Prioridad', key: 'Media', color: 'var(--warning)', bg: 'var(--warning-light)', text: 'var(--warning-dark)', icon: '🟡' },
                        { name: 'Baja Prioridad', key: 'Baja', color: 'var(--primary)', bg: 'var(--primary-light)', text: 'var(--primary-dark)', icon: '🔵' }
                    ];

                    const groupsHtml = groupConfig.map(c => {
                        const appts = groups[c.key];
                        if (appts.length === 0) return '';
                        return `
                            <div style="margin-bottom: 2rem;">
                                <div style="display:flex; align-items:center; gap:.5rem; padding:.5rem 1rem; background:${c.bg}; border-left:4px solid ${c.color}; border-radius:var(--radius); margin-bottom:1rem;">
                                    <span style="font-size:1.2rem;">${c.icon}</span>
                                    <h3 style="margin:0; font-size:1rem; color:${c.text}; font-weight:700;">${c.name} (${appts.length})</h3>
                                </div>
                                <div style="display:grid; grid-template-columns: 1fr; gap: .75rem; padding-left:.5rem;">
                                    ${appts.map(a => renderCard(a)).join('')}
                                </div>
                            </div>
                        `;
                    }).join('');

                    content.innerHTML = bannerHtml + groupsHtml;

                } else {
                    // Chronological view
                    const byHour = {};
                    appointments.sort((a,b) => new Date(a.start_time) - new Date(b.start_time)).forEach(a => {
                        const hour = UI.formatTime(a.start_time);
                        if (!byHour[hour]) byHour[hour] = [];
                        byHour[hour].push(a);
                    });

                    const slotsHtml = Object.entries(byHour).map(([hour, appts]) => `
                        <div class="agenda-slot">
                            <div class="slot-time">${hour}</div>
                            <div class="slot-cards">
                                ${appts.map(a => renderCard(a)).join('')}
                            </div>
                        </div>
                    `).join('');

                    content.innerHTML = bannerHtml + slotsHtml;
                }
            } else if (state.view === 'week') {
                const days = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
                const startDate = new Date(dateFrom.split('T')[0] + 'T12:00:00');
                const START_HOUR = 8, END_HOUR = 21;
                const SLOT_H = 28;

                // Header row
                let hdrHtml = '<div class="wk-time-gutter wk-header-cell"></div>';
                const dayDates = [];
                for (let i = 0; i < 7; i++) {
                    const cur = new Date(startDate); cur.setDate(startDate.getDate() + i);
                    const iso = cur.toISOString().split('T')[0];
                    dayDates.push(iso);
                    hdrHtml += `<div class="wk-header-cell ${iso === today ? 'current-day' : ''}">
                        <div class="wk-day-name">${days[i]}</div>
                        <div class="wk-day-num">${cur.getDate()}</div>
                    </div>`;
                }

                // Time column + day columns
                let bodyHtml = '<div class="wk-time-gutter">';
                for (let h = START_HOUR; h < END_HOUR; h++) {
                    bodyHtml += `<div class="wk-time-label" style="height:${SLOT_H * 2}px">${String(h).padStart(2,'0')}:00</div>`;
                }
                bodyHtml += '</div>';

                // Each day column
                dayDates.forEach(iso => {
                    const dayAppts = appointments.filter(a => a.start_time.startsWith(iso));
                    let slotsHtml = '';
                    for (let h = START_HOUR; h < END_HOUR; h++) {
                        for (let m = 0; m < 60; m += 30) {
                            const t = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
                            slotsHtml += `<div class="wk-slot ${m === 0 ? 'wk-slot-hour' : ''}" data-date="${iso}" data-time="${t}" ondblclick="AgendaPage.quickNew('${iso}','${t}')"></div>`;
                        }
                    }

                    // Position events
                    let eventsHtml = '';
                    dayAppts.forEach(a => {
                        const dt = new Date(a.start_time);
                        const mins = (dt.getHours() - START_HOUR) * 60 + dt.getMinutes();
                        if (mins < 0) return;
                        const top = mins * SLOT_H / 30;
                        const dur = a.duration_minutes || 30;
                        const height = Math.max(dur * SLOT_H / 30, SLOT_H);
                        const hasConflict = conflictIds.has(a.id);
                        const pri = a.treatment_priority || '';
                        eventsHtml += `<div class="wk-event status-${a.status} ${hasConflict ? 'wk-conflict' : ''}" style="top:${top}px;height:${height}px" onclick="AgendaPage.showAppointment('${a.id}')">
                            <strong>${UI.formatTime(a.start_time)}</strong> ${a.patient ? a.patient.last_name : ''}
                            ${hasConflict ? '<span class="wk-conflict-icon">⚠️</span>' : ''}
                            ${pri ? `<span class="wk-pri wk-pri-${pri.toLowerCase()}">${pri}</span>` : ''}
                        </div>`;
                    });

                    bodyHtml += `<div class="wk-day-col" data-date="${iso}">${slotsHtml}<div class="wk-events-layer">${eventsHtml}</div></div>`;
                });

                // Conflict banner
                let bannerHtml = '';
                if (conflictIds.size > 0) {
                    bannerHtml = `<div style="background:var(--danger-light);border:1px solid var(--danger);border-radius:var(--radius);padding:.6rem 1rem;margin-bottom:.75rem;font-size:.85rem;color:var(--danger);font-weight:600;">⚠️ Turnos superpuestos detectados</div>`;
                }

                content.innerHTML = bannerHtml + `<div class="wk-calendar"><div class="wk-header">${hdrHtml}</div><div class="wk-body">${bodyHtml}</div></div>`;
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
                                const hasConflict = conflictIds.has(a.id);
                                return `
                                    <div class="mini-appt status-${a.status}" 
                                         onclick="AgendaPage.showAppointment('${a.id}')"
                                         style="${hasConflict ? 'border-left: 3px solid var(--danger) !important; font-weight:700;' : ''}">
                                        <span>${hasConflict ? '⚠️' : (icons[a.status] || '')}</span>
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

    ['agenda-date', 'agenda-prof', 'agenda-location', 'agenda-status', 'agenda-grouping'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', (e) => {
            if (id === 'agenda-date') state.currentDate = e.target.value;
            loadAgenda();
        });
    });

    const btnNew = document.getElementById('btn-new-appointment');
    if (btnNew) btnNew.onclick = () => AgendaPage.showNewAppointment(professionals);

    // Exponer la función para recargar desde fuera
    AgendaPage.loadAgenda = loadAgenda;

    // Auto-refresh every 30 seconds
    let agendaInterval = setInterval(() => {
        if (document.getElementById('agenda-content')) {
            loadAgenda();
        } else {
            clearInterval(agendaInterval);
        }
    }, 30000);

    loadAgenda();
});

const AgendaPage = {
    _pendingAppts: [],

    async showAppointment(id) {
        try {
            const a = await API.getAppointment(id);
            let professionals = [];
            try { professionals = await API.getProfessionals(); } catch (e) {}

            const p = a.patient || {};
            // Escapa un valor para usarlo dentro de un atributo HTML (value="...")
            const attr = (v) => String(v == null ? '' : v)
                .replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
            const profOptions = professionals.map(pr =>
                `<option value="${pr.id}" ${a.professional_id === pr.id ? 'selected' : ''}>${attr(pr.full_name)}</option>`
            ).join('');
            const startVal = (a.start_time || '').slice(0, 16); // YYYY-MM-DDTHH:MM para datetime-local
            const obra = a.insurance_name || p.insurance_name || '';
            const st = a.status;

            UI.showModal('Detalle del Turno', `
                <div class="form-grid">
                    <div class="form-group"><label>Apellido</label><input id="edit-last" class="form-control" value="${attr(p.last_name)}"></div>
                    <div class="form-group"><label>Nombre</label><input id="edit-first" class="form-control" value="${attr(p.first_name)}"></div>
                    <div class="form-group"><label>DNI</label><input id="edit-dni" class="form-control" value="${attr(p.dni)}"></div>
                    <div class="form-group"><label>Teléfono</label><input id="edit-phone" class="form-control" value="${attr(p.phone)}"></div>
                    <div class="form-group"><label>Obra Social</label><input id="edit-insurance" class="form-control" value="${attr(obra)}"></div>
                    <div class="form-group"><label>Profesional</label><select id="edit-prof" class="form-control">${profOptions}</select></div>
                    <div class="form-group"><label>Fecha/Hora</label><input id="edit-start" type="datetime-local" class="form-control" value="${startVal}"></div>
                    <div class="form-group"><label>Motivo</label><input id="edit-reason" class="form-control" value="${attr(a.reason)}"></div>
                    <div class="form-group">
                        <label>Estado</label>
                        <select id="edit-status" class="form-control">
                            <option value="pending" ${st==='pending'?'selected':''}>⏳ Pendiente</option>
                            <option value="confirmed" ${st==='confirmed'?'selected':''}>✅ Confirmado</option>
                            <option value="completed" ${st==='completed'?'selected':''}>🏁 Realizado</option>
                            <option value="cancelled" ${st==='cancelled'?'selected':''}>❌ Cancelado</option>
                            <option value="no_show" ${st==='no_show'?'selected':''}>🚫 No asistió</option>
                        </select>
                    </div>
                </div>
            `, `
                <button class="btn btn-secondary" onclick="UI.closeModal()">Cerrar</button>
                <button class="btn btn-primary" onclick="AgendaPage.saveAppointment('${a.id}', '${p.id || ''}')">Guardar cambios</button>
            `);
        } catch (err) { UI.toast(err.message, 'error'); }
    },

    async saveAppointment(apptId, patientId) {
        const val = (id) => (document.getElementById(id)?.value || '').trim();
        try {
            // 1) Datos del paciente
            if (patientId) {
                const patientData = {
                    first_name: val('edit-first'),
                    last_name: val('edit-last'),
                    phone: val('edit-phone'),
                    insurance_name: val('edit-insurance'),
                };
                const dni = val('edit-dni');
                if (dni) patientData.dni = dni; // no mandar DNI vacío
                await API.updatePatient(patientId, patientData);
            }
            // 2) Datos del turno
            const startVal = val('edit-start');
            const apptData = {
                reason: val('edit-reason') || null,
                professional_id: val('edit-prof'),
                insurance_name: val('edit-insurance'),
                status: val('edit-status'),
            };
            if (startVal) apptData.start_time = startVal;
            await API.updateAppointment(apptId, apptData);

            UI.toast('Turno actualizado', 'success');
            UI.closeModal();
            if (AgendaPage.loadAgenda) AgendaPage.loadAgenda();
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

    async quickNew(date, time) {
        const dt = `${date}T${time}`;
        let professionals = [];
        try { professionals = await API.getProfessionals(); } catch(e) {}
        this._showMultiModal(professionals, dt);
    },

    async showNewAppointment(professionals = []) {
        this._showMultiModal(professionals, UI.nowISO());
    },

    _showMultiModal(professionals, defaultDateTime) {
        this._pendingAppts = [];
        let patients = [];
        API.getPatients().then(p => { patients = p; this._renderMultiModal(professionals, patients, defaultDateTime); });
    },

    _renderMultiModal(professionals, patients, defaultDateTime) {
        this._modalPatients = patients;
        const listHtml = () => this._pendingAppts.map((a, i) => {
            const pat = patients.find(p => p.id === a.patient_id);
            return `<div class="pending-appt-item"><span>🕐 ${a.start_time.replace('T',' ')} — ${pat ? pat.last_name + ', ' + pat.first_name : '?'} — ${a.reason || 'Sin motivo'}</span><button class="btn btn-sm btn-ghost" onclick="AgendaPage._removePending(${i})" style="color:var(--danger)">✕</button></div>`;
        }).join('');

        UI.showModal('Nuevo Turno', `
            <div id="multi-appt-list" style="margin-bottom:1rem;">${listHtml()}</div>
            <form id="form-new-appointment" class="form-grid">
                <div class="form-group">
                    <label>Paciente *</label>
                    <input type="text" id="appt-patient-search" placeholder="Buscar por nombre, apellido o DNI..." style="margin-bottom:.35rem;" oninput="AgendaPage._filterPatients(this.value)">
                    <select name="patient_id" id="appt-patient-select" required>
                        <option value="">Seleccionar...</option>
                        ${patients.map(p => `<option value="${p.id}">${p.last_name}, ${p.first_name}</option>`).join('')}
                    </select>
                    <button type="button" class="btn btn-sm btn-ghost" style="margin-top:.35rem;color:var(--primary);" onclick="AgendaPage._toggleNewPatient()">+ Nuevo paciente</button>
                    <div id="appt-new-patient" style="display:none;margin-top:.5rem;padding:.75rem;background:var(--slate-50);border-radius:8px;border:1px solid var(--slate-200);">
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem;">
                            <input type="text" id="np-first" placeholder="Nombre *">
                            <input type="text" id="np-last" placeholder="Apellido *">
                            <input type="text" id="np-dni" placeholder="DNI *">
                            <input type="text" id="np-phone" placeholder="Teléfono *">
                        </div>
                        <button type="button" class="btn btn-sm btn-primary" style="margin-top:.5rem;" onclick="AgendaPage._createPatientInline()">Crear y seleccionar</button>
                    </div>
                </div>
                <div class="form-group">
                    <label>Profesional *</label>
                    <select name="professional_id" required>
                        ${professionals.map(p => `<option value="${p.id}">${p.full_name}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>Fecha y Hora *</label>
                    <input type="datetime-local" name="start_time" required value="${defaultDateTime}">
                </div>
                <div class="form-group">
                    <label>Duración (min)</label>
                    <input type="number" name="duration_minutes" value="30" min="15" step="15">
                </div>
                <div class="form-group form-group-full">
                    <label>Motivo</label>
                    <textarea name="reason"></textarea>
                </div>
            </form>
        `, `
            <button class="btn btn-secondary" onclick="UI.closeModal()">Cancelar</button>
            <button class="btn btn-ghost" onclick="AgendaPage._addToList()" style="border-color:var(--primary);color:var(--primary)">+ Agregar a Lista</button>
            <button class="btn btn-primary" onclick="AgendaPage._saveAll()">Guardar${this._pendingAppts.length > 0 ? ` (${this._pendingAppts.length + 1})` : ''}</button>
        `);
    },

    _addToList() {
        const data = UI.getFormData('form-new-appointment');
        if (!data.patient_id || !data.start_time) return UI.toast('Completá paciente y fecha', 'error');
        this._pendingAppts.push({...data, duration_minutes: parseInt(data.duration_minutes) || 30});
        const listEl = document.getElementById('multi-appt-list');
        if (listEl) {
            const pat = document.querySelector('[name="patient_id"] option:checked');
            listEl.innerHTML += `<div class="pending-appt-item"><span>🕐 ${data.start_time.replace('T',' ')} — ${pat ? pat.textContent : '?'} — ${data.reason || 'Sin motivo'}</span><button class="btn btn-sm btn-ghost" onclick="AgendaPage._removePending(${this._pendingAppts.length - 1})" style="color:var(--danger)">✕</button></div>`;
        }
        // Reset form time +30min
        const timeInput = document.querySelector('[name="start_time"]');
        if (timeInput) {
            const d = new Date(data.start_time); d.setMinutes(d.getMinutes() + 30);
            timeInput.value = d.toISOString().slice(0,16);
        }
        UI.toast(`Turno agregado a lista (${this._pendingAppts.length})`, 'info');
    },

    _removePending(idx) {
        this._pendingAppts.splice(idx, 1);
        const items = document.querySelectorAll('.pending-appt-item');
        if (items[idx]) items[idx].remove();
    },

    // Buscador de paciente en el modal de Nuevo Turno
    _filterPatients(q) {
        q = (q || '').trim().toLowerCase();
        const sel = document.getElementById('appt-patient-select');
        if (!sel) return;
        const current = sel.value;
        const list = !q ? this._modalPatients : this._modalPatients.filter(p =>
            `${p.last_name} ${p.first_name} ${p.dni}`.toLowerCase().includes(q));
        sel.innerHTML = '<option value="">Seleccionar...</option>' +
            list.map(p => `<option value="${p.id}" ${p.id === current ? 'selected' : ''}>${p.last_name}, ${p.first_name}</option>`).join('');
    },

    _toggleNewPatient() {
        const el = document.getElementById('appt-new-patient');
        if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
    },

    async _createPatientInline() {
        const g = id => (document.getElementById(id)?.value || '').trim();
        const data = { first_name: g('np-first'), last_name: g('np-last'), dni: g('np-dni'), phone: g('np-phone') };
        if (!data.first_name || !data.last_name || !data.dni || !data.phone) {
            return UI.toast('Completá nombre, apellido, DNI y teléfono', 'error');
        }
        try {
            const p = await API.createPatient(data);
            this._modalPatients.push(p);
            const sel = document.getElementById('appt-patient-select');
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = `${p.last_name}, ${p.first_name}`;
            opt.selected = true;
            sel.appendChild(opt);
            document.getElementById('appt-new-patient').style.display = 'none';
            UI.toast('Paciente creado y seleccionado', 'success');
        } catch (e) { UI.toast(e.message || 'Error al crear paciente', 'error'); }
    },

    async _saveAll() {
        const formData = UI.getFormData('form-new-appointment');
        const allAppts = [...this._pendingAppts];
        if (formData.patient_id && formData.start_time) {
            allAppts.push({...formData, duration_minutes: parseInt(formData.duration_minutes) || 30});
        }
        if (allAppts.length === 0) return UI.toast('Agregá al menos un turno', 'error');

        let ok = 0, fail = 0;
        for (const appt of allAppts) {
            try {
                await API.createAppointment(appt);
                ok++;
            } catch (err) { fail++; }
        }
        this._pendingAppts = [];
        UI.closeModal();
        UI.toast(`${ok} turno(s) creado(s)${fail ? `, ${fail} con error` : ''}`, ok > 0 ? 'success' : 'error');
        if (AgendaPage.loadAgenda) AgendaPage.loadAgenda();
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

