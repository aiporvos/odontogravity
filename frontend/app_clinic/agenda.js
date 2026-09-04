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

    // Sillones por sede: define cuando dos turnos superpuestos son un
    // problema real (mas turnos que sillones) o algo que la sede absorbe.
    // Se trae una sola vez al entrar a la pagina, no en cada refresco de la
    // agenda (que corre cada 30s).
    try {
        const cfg = await API.getAgendaConfig();
        AgendaPage._chairsPerLocation = cfg.chairs_per_location || 1;
    } catch (e) {
        AgendaPage._chairsPerLocation = 1;
    }

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

    // `silencioso` es el refresco de fondo cada 30 segundos: pide los datos,
    // y solo toca el DOM si algo cambio de verdad. Sin eso la agenda se
    // repintaba entera sola cada medio minuto —parpadeo, scroll al tope y el
    // hover cortado justo cuando alguien iba a hacer clic en un turno.
    async function loadAgenda({ silencioso = false } = {}) {
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

        // Dos cargas encimadas (el refresco de fondo y un clic del usuario)
        // llegaban en cualquier orden y la mas vieja podia pisar a la nueva.
        const token = (state.tokenDeCarga || 0) + 1;
        state.tokenDeCarga = token;

        // El spinner no sale de entrada: se agenda para dentro de 250 ms y
        // casi siempre se cancela antes, porque la respuesta llega primero.
        // Asi cambiar de dia deja de tener un parpadeo blanco en el medio, y
        // el spinner queda para cuando la espera se nota de verdad.
        let spinnerTimer = null;
        if (!silencioso) {
            spinnerTimer = setTimeout(() => {
                if (state.tokenDeCarga === token) {
                    content.innerHTML = '<div class="loading-page"><div class="spinner"></div></div>';
                }
            }, 250);
        }

        const pintar = (html) => {
            clearTimeout(spinnerTimer);
            // Llego tarde: ya hay una carga mas nueva en curso.
            if (state.tokenDeCarga !== token) return;
            // En el refresco de fondo, si el resultado es identico a lo que ya
            // esta en pantalla no se toca nada. Es el caso normal: la mayoria
            // de los refrescos no traen ninguna novedad.
            if (silencioso && html === state.ultimoHtml) return;
            state.ultimoHtml = html;
            // Reemplazar el innerHTML manda el scroll al tope. En el refresco
            // de fondo eso es una pantalla que se mueve sola mientras alguien
            // esta leyendo, asi que se restituye.
            //
            // Quien scrollea es #page-container, no la ventana: el body tiene
            // overflow:hidden, asi que window.scrollY vale 0 siempre y
            // guardarlo no restituia nada.
            const scroller = document.getElementById('page-container');
            const scroll = scroller ? scroller.scrollTop : 0;
            content.innerHTML = html;
            if (silencioso && scroller) scroller.scrollTop = scroll;
        };

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

            // Deteccion de conflictos: mismo profesional al mismo tiempo, o mas
            // turnos superpuestos que sillones tiene la sede. Antes solo miraba
            // "mismo profesional", asi que un sobreturno con OTRO profesional en
            // el mismo sillon no disparaba ningun aviso.
            const chairs = AgendaPage._chairsPerLocation || 1;
            const conflictIds = new Set();     // cualquiera dentro de un conflicto (para el banner)
            const sobreturnoIds = new Set();   // solo el/los turno(s) creados DESPUES del primero
            const activeAppts = appointments.filter(a => a.status !== 'cancelled');
            for (let i = 0; i < activeAppts.length; i++) {
                const a = activeAppts[i];
                const aStart = new Date(a.start_time).getTime();
                const aEnd = aStart + (a.duration_minutes || 30) * 60 * 1000;
                const overlapping = [a];
                for (let j = 0; j < activeAppts.length; j++) {
                    if (i === j) continue;
                    const b = activeAppts[j];
                    // Una sede en blanco cuenta como "cualquier sede", igual que en el
                    // backend (get_day_appointments): dos turnos con sede vacia u
                    // distinta-de-vacia-y-otra-vacia siguen compitiendo por el mismo
                    // sillon fisico. Comparacion estricta solo cuando AMBAS estan
                    // cargadas y son distintas.
                    if (a.location && b.location && a.location !== b.location) continue;
                    const bStart = new Date(b.start_time).getTime();
                    const bEnd = bStart + (b.duration_minutes || 30) * 60 * 1000;
                    if (aStart < bEnd && bStart < aEnd) overlapping.push(b);
                }
                if (overlapping.length <= 1) continue;

                const mismoProfesional = overlapping.some(x => x !== a && x.professional_id === a.professional_id);
                const superaSillones = overlapping.length > chairs;
                if (!mismoProfesional && !superaSillones) continue;

                overlapping.forEach(x => conflictIds.add(x.id));
                // El turno "original" es el de created_at mas antiguo del grupo; el
                // resto son sobreturnos (el/los que se agregaron encima despues).
                const original = overlapping.reduce((min, x) =>
                    new Date(x.created_at) < new Date(min.created_at) ? x : min);
                overlapping.forEach(x => { if (x.id !== original.id) sobreturnoIds.add(x.id); });
            }

            const grouping = document.getElementById('agenda-grouping')?.value || 'chronological';

            if (state.view === 'day') {
                if (appointments.length === 0) {
                    return pintar(`<div class="empty-state"><div class="empty-state-text">No hay turnos hoy</div></div>`);
                }

                // Show conflict banner if there are conflicts
                let bannerHtml = '';
                if (conflictIds.size > 0) {
                    bannerHtml = `
                        <div class="card" style="background:var(--danger-light); border-color:var(--danger); margin-bottom:1.5rem; padding: 1rem;">
                            <div style="display:flex; gap:1rem; align-items:center;">
                                <div style="font-size:1.5rem;">⚠️</div>
                                <div style="font-size:.9rem; color:var(--danger-dark); font-weight: 600;">
                                    Sobreturno: hay más turnos agendados que los que la sede puede atender a esa hora.
                                </div>
                            </div>
                        </div>
                    `;
                }

                // Render card function helper
                const renderCard = (a) => {
                    const icons = { pending:'⏳', confirmed:'✅', completed:'🏁', cancelled:'❌', no_show:'🚫' };
                    // El aviso va SOLO en el turno que se agrego encima (el creado
                    // despues); el original queda con su apariencia normal, sin
                    // marca, para que quede claro cual es el "extra".
                    // La marca la trae el turno: se decidio al cargarlo. El
                    // calculo por created_at queda de respaldo para los turnos
                    // anteriores a que existiera el campo — esa deduccion se
                    // mudaba sola si el original se cancelaba.
                    const esSobreturno = a.is_overbooking === true || sobreturnoIds.has(a.id);
                    const pri = a.treatment_priority || 'Baja';
                    const priorityClass = pri === 'Alta' ? 'badge-cancelled' : (pri === 'Media' ? 'badge-pending' : 'badge-confirmed');
                    
                    const conflictBadge = esSobreturno ? `
                        <span class="badge badge-pending" style="font-weight:700; display:inline-flex; align-items:center; gap:0.25rem;">
                            🔶 Sobreturno
                        </span>
                    ` : '';

                    return `
                        <div class="appointment-card status-${a.status}" 
                             onclick="AgendaPage.showAppointment('${a.id}')"
                             style="${esSobreturno ? 'border-left-color: var(--warning); outline: 2px solid var(--warning);' : ''}">
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

                    pintar(bannerHtml + groupsHtml);

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

                    pintar(bannerHtml + slotsHtml);
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
                    //
                    // Los turnos van posicionados en absoluto y ocupaban el
                    // ancho entero de la columna, asi que dos a la misma hora se
                    // tapaban: se veia uno solo. Justo el caso del sobreturno.
                    const ubicacion = AgendaPage._repartirEnColumnas(dayAppts);
                    let eventsHtml = '';
                    dayAppts.forEach(a => {
                        const dt = new Date(a.start_time);
                        const mins = (dt.getHours() - START_HOUR) * 60 + dt.getMinutes();
                        if (mins < 0) return;
                        const top = mins * SLOT_H / 30;
                        const dur = a.duration_minutes || 30;
                        const height = Math.max(dur * SLOT_H / 30, SLOT_H);
                        const esSobreturno = a.is_overbooking === true || sobreturnoIds.has(a.id);
                        const pri = a.treatment_priority || '';
                        const { columna, columnas } = ubicacion.get(a.id) || { columna: 0, columnas: 1 };
                        const ancho = 100 / columnas;
                        // `right:auto` porque la regla de .wk-event fija right:2px
                        // para ocupar todo el ancho.
                        const lado = `left:calc(${columna * ancho}% + 2px);width:calc(${ancho}% - 4px);right:auto;`;
                        eventsHtml += `<div class="wk-event status-${a.status} ${esSobreturno ? 'wk-conflict' : ''}" style="top:${top}px;height:${height}px;${lado}" onclick="AgendaPage.showAppointment('${a.id}')">
                            <strong>${UI.formatTime(a.start_time)}</strong> ${a.patient ? a.patient.last_name : ''}
                            ${esSobreturno ? '<span class="wk-conflict-icon" title="Sobreturno">🔶</span>' : ''}
                            ${pri ? `<span class="wk-pri wk-pri-${pri.toLowerCase()}">${pri}</span>` : ''}
                        </div>`;
                    });

                    bodyHtml += `<div class="wk-day-col" data-date="${iso}">${slotsHtml}<div class="wk-events-layer">${eventsHtml}</div></div>`;
                });

                // Conflict banner
                let bannerHtml = '';
                if (conflictIds.size > 0) {
                    bannerHtml = `<div style="background:var(--danger-light);border:1px solid var(--danger);border-radius:var(--radius);padding:.6rem 1rem;margin-bottom:.75rem;font-size:.85rem;color:var(--danger);font-weight:600;">⚠️ Hay sobreturnos esta semana</div>`;
                }

                pintar(bannerHtml + `<div class="wk-calendar"><div class="wk-header">${hdrHtml}</div><div class="wk-body">${bodyHtml}</div></div>`);
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
                pintar(html);
            }
        } catch (err) {
            clearTimeout(spinnerTimer);
            // Un corte de red en el refresco de fondo no puede borrar la
            // agenda que alguien esta mirando: se deja lo que hay y se
            // reintenta en el proximo ciclo.
            if (silencioso) {
                console.warn('Refresco de agenda fallido, se reintenta:', err.message);
                return;
            }
            if (state.tokenDeCarga === token) {
                content.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error: ${err.message}</div></div>`;
            }
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

    // Refresco de fondo cada 30 segundos, en silencio.
    const conviene_refrescar = () =>
        !!document.getElementById('agenda-content')
        // Pestania en segundo plano: no tiene sentido pedir nada.
        && !document.hidden
        // Con un modal abierto la agenda de atras no se toca: alguien esta
        // cargando un turno y no necesita que se le mueva la pantalla.
        && !(typeof UI !== 'undefined' && UI.modalAbierto());

    let agendaInterval = setInterval(() => {
        if (!document.getElementById('agenda-content')) return clearInterval(agendaInterval);
        if (conviene_refrescar()) loadAgenda({ silencioso: true });
    }, 30000);

    // Al volver a la pestania, ponerse al dia en el acto: si no, se miran
    // datos de hasta 30 segundos atras sin saberlo.
    if (!AgendaPage._miraLaVisibilidad) {
        AgendaPage._miraLaVisibilidad = true;
        document.addEventListener('visibilitychange', () => {
            if (conviene_refrescar()) AgendaPage.loadAgenda?.({ silencioso: true });
        });
    }

    loadAgenda();
});

const AgendaPage = {
    _pendingAppts: [],

    // Reparte los turnos de un dia en columnas para que los que se pisan queden
    // lado a lado en vez de uno encima del otro. Devuelve id -> {columna, columnas}.
    //
    // Se arman grupos de turnos encadenados por solapamiento y dentro de cada
    // grupo cada turno toma la primera columna libre. El ancho se divide entre
    // las columnas que ese grupo llego a necesitar, no entre todas las del dia:
    // un par de sobreturnos a las 9 no tiene por que angostar la tarde entera.
    _repartirEnColumnas(turnos) {
        const ubicacion = new Map();
        const enOrden = [...turnos].sort(
            (a, b) => new Date(a.start_time) - new Date(b.start_time));

        const fin = (t) => new Date(t.start_time).getTime() + (t.duration_minutes || 30) * 60000;
        const inicio = (t) => new Date(t.start_time).getTime();

        let grupo = [];          // turnos del grupo actual, con su columna asignada
        let finDelGrupo = -Infinity;

        const cerrarGrupo = () => {
            if (!grupo.length) return;
            const columnas = Math.max(...grupo.map(g => g.columna)) + 1;
            grupo.forEach(g => ubicacion.set(g.turno.id, { columna: g.columna, columnas }));
            grupo = [];
            finDelGrupo = -Infinity;
        };

        enOrden.forEach(t => {
            // Arranca despues de que termino todo el grupo: es un grupo nuevo.
            if (inicio(t) >= finDelGrupo) cerrarGrupo();

            const ocupadas = new Set(
                grupo.filter(g => fin(g.turno) > inicio(t)).map(g => g.columna));
            let columna = 0;
            while (ocupadas.has(columna)) columna++;

            grupo.push({ turno: t, columna });
            finDelGrupo = Math.max(finDelGrupo, fin(t));
        });
        cerrarGrupo();

        return ubicacion;
    },

    async showAppointment(id) {
        try {
            const a = await API.getAppointment(id);
            let professionals = [], locations = [];
            try { professionals = await API.getProfessionals(); } catch (e) {}
            try { locations = await API.getClinicLocations(); } catch (e) {}

            const p = a.patient || {};
            // Escapa un valor para usarlo dentro de un atributo HTML (value="...")
            const attr = (v) => String(v == null ? '' : v)
                .replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
            const profOptions = professionals.map(pr =>
                `<option value="${pr.id}" ${a.professional_id === pr.id ? 'selected' : ''}>${attr(pr.full_name)}</option>`
            ).join('');
            // Sede: los turnos viejos la tienen vacía y así el bot no los ve al
            // calcular disponibilidad. Se puede corregir desde acá.
            const locOptions = locations.map(l =>
                `<option value="${attr(l.name)}" ${a.location === l.name ? 'selected' : ''}>${attr(l.name)}</option>`
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
                    <div class="form-group"><label>Fecha/Hora</label>${AgendaPage._dateTimeFieldsHTML('edit', startVal, 'id="edit-start"')}</div>
                    <div class="form-group">
                        <label>Sede${a.location ? '' : ' ⚠️ sin asignar'}</label>
                        <select id="edit-location" class="form-control">
                            <option value="">Sin asignar</option>${locOptions}
                        </select>
                    </div>
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
                ${API.user?.role === 'admin' ? `
                    <button class="btn btn-danger" style="margin-right:auto;" onclick="AgendaPage.deletePermanent('${a.id}')">🗑️ Borrar definitivamente</button>
                ` : ''}
                <button class="btn btn-secondary" onclick="UI.closeModal()">Cerrar</button>
                <button class="btn btn-primary" onclick="AgendaPage.saveAppointment('${a.id}', '${p.id || ''}')">Guardar cambios</button>
            `);
        } catch (err) { UI.toast(err.message, 'error'); }
    },

    async deletePermanent(apptId) {
        // Distinto de "Cancelado": ese estado deja el turno en el historial (para
        // saber por que el paciente no vino). Esto lo saca de la base para
        // siempre, para lo que ni siquiera merece quedar como cancelado: turnos
        // de prueba, duplicados por un doble clic, datos cargados mal.
        const ok = await UI.confirm(
            'Borrar turno definitivamente',
            'Esta acción NO se puede deshacer y es distinta de cancelar: el turno desaparece de la base, no queda en el historial. ¿Continuar?'
        );
        if (!ok) return;
        try {
            await API.deleteAppointmentPermanent(apptId);
            UI.toast('Turno borrado', 'success');
            UI.closeModal();
            if (AgendaPage.loadAgenda) AgendaPage.loadAgenda();
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
            const loc = val('edit-location');
            if (loc) apptData.location = loc;
            await this._guardarConSobreturno(apptData, (d) => API.updateAppointment(apptId, d));

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
        this._locationsFailed = false;
        // Los feriados se traen junto con los pacientes para poder avisar en el
        // momento, sin esperar a que el backend rechace el turno.
        Promise.all([
            API.getPatients(),
            API.getHolidays().catch(() => []),
            API.getClinicLocations().catch(() => { this._locationsFailed = true; return []; }),
        ]).then(([patients, holidays, locations]) => {
            this._holidays = holidays || [];
            this._locations = locations || [];
            // Antes esto se tragaba en silencio: si la lista de sedes no cargaba
            // (o no había ninguna activa), el desplegable de Sede quedaba vacío
            // y, al ser un campo obligatorio, el navegador bloqueaba el botón
            // Guardar sin explicar por qué. Ahora se avisa y el campo deja de
            // ser obligatorio en ese caso puntual, para no trabar la carga de
            // turnos por un problema ajeno al usuario.
            if (this._locationsFailed) {
                UI.toast('No se pudo cargar la lista de sedes. Se puede guardar sin asignar sede.', 'error');
            } else if (this._locations.length === 0) {
                UI.toast('No hay ninguna sede activa cargada (revisá Configuración → Sedes).', 'error');
            }
            this._renderMultiModal(professionals, patients, defaultDateTime);
        });
    },

    // Devuelve el feriado que cae en esa fecha, o null.
    _holidayFor(dateTimeLocal) {
        if (!dateTimeLocal) return null;
        const day = String(dateTimeLocal).slice(0, 10); // YYYY-MM-DD
        return (this._holidays || []).find(h => h.date === day) || null;
    },

    _holidayMsg(h) {
        const [y, m, d] = h.date.split('-');
        return `El ${d}/${m}/${y} es feriado${h.description ? ` (${h.description})` : ''}. La clínica está cerrada.`;
    },

    // Aviso en vivo debajo del campo de fecha.
    _checkHoliday(value) {
        const box = document.getElementById('appt-holiday-warning');
        if (!box) return;
        const h = this._holidayFor(value);
        box.style.display = h ? 'block' : 'none';
        box.textContent = h ? `⛔ ${this._holidayMsg(h)}` : '';
    },

    // ── Selector de Fecha y Hora (reemplaza <input type="datetime-local">) ──
    // El picker nativo no abre de forma confiable en todos los navegadores (a
    // veces no "despliega nada" salvo que se clickee el icono exacto) y el
    // formato de hora depende del locale del sistema operativo, asi que a
    // veces se ve en 12h con AM/PM. Un <input type="date"> mas dos <select>
    // de hora/minuto son robustos en cualquier navegador y fuerzan 24h siempre.
    //
    // idPrefix: 'appt' (nuevo turno) o 'edit' (editar turno). hiddenAttr es el
    // atributo (name="..." o id="...") que el resto del codigo espera leer:
    // UI.getFormData busca por name, y saveAppointment por getElementById.
    _dateTimeFieldsHTML(idPrefix, isoValue, hiddenAttr) {
        const [datePart, timePart] = (isoValue || '').split('T');
        const hh = timePart ? parseInt(timePart.slice(0, 2), 10) : null;
        const mm = timePart ? parseInt(timePart.slice(3, 5), 10) : null;

        const hourOpts = Array.from({ length: 24 }, (_, h) => {
            const v = String(h).padStart(2, '0');
            return `<option value="${v}" ${h === hh ? 'selected' : ''}>${v}</option>`;
        }).join('');

        // Minutos cada 5, mas el valor real si no cae en esa grilla (para no
        // "correr" turnos ya cargados con minutos sueltos, ej. :41).
        const minutos = new Set([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]);
        if (mm !== null) minutos.add(mm);
        const minOpts = [...minutos].sort((a, b) => a - b).map(m => {
            const v = String(m).padStart(2, '0');
            return `<option value="${v}" ${m === mm ? 'selected' : ''}>${v}</option>`;
        }).join('');

        return `
            <div style="display:flex;gap:.4rem;align-items:center;">
                <input type="date" id="${idPrefix}-date" class="form-control" style="flex:1.6;"
                    value="${datePart || ''}" required
                    onchange="AgendaPage._onDateTimeChange('${idPrefix}')">
                <select id="${idPrefix}-hour" class="form-control" style="flex:1;"
                    onchange="AgendaPage._onDateTimeChange('${idPrefix}')">${hourOpts}</select>
                <span style="font-weight:700;">:</span>
                <select id="${idPrefix}-min" class="form-control" style="flex:1;"
                    onchange="AgendaPage._onDateTimeChange('${idPrefix}')">${minOpts}</select>
            </div>
            <input type="hidden" ${hiddenAttr} value="${isoValue || ''}">
        `;
    },

    // Junta los 3 controles visibles en "YYYY-MM-DDTHH:MM" y lo guarda en el
    // input oculto, que es lo que lee el resto del codigo (getFormData / val()).
    _syncDateTimeFields(idPrefix) {
        const d = document.getElementById(`${idPrefix}-date`)?.value;
        const h = document.getElementById(`${idPrefix}-hour`)?.value;
        const m = document.getElementById(`${idPrefix}-min`)?.value;
        if (!d || h === undefined || m === undefined) return null;
        return `${d}T${h}:${m}`;
    },

    // Pone fecha/hora en los 3 controles visibles Y en el input oculto,
    // manteniendolos siempre en sincronia (por ejemplo al avanzar +30min
    // despues de "Agregar a Lista").
    _setDateTimeFields(idPrefix, isoValue) {
        const [datePart, timePart] = (isoValue || '').split('T');
        const dateEl = document.getElementById(`${idPrefix}-date`);
        const hourEl = document.getElementById(`${idPrefix}-hour`);
        const minEl = document.getElementById(`${idPrefix}-min`);
        if (dateEl) dateEl.value = datePart || '';
        if (hourEl && timePart) hourEl.value = timePart.slice(0, 2);
        if (minEl && timePart) {
            const mm = timePart.slice(3, 5);
            // Si el minuto no esta en la grilla de a 5, se agrega como opcion
            // nueva (igual que hace _dateTimeFieldsHTML al renderizar).
            if (![...minEl.options].some(o => o.value === mm)) {
                const opt = document.createElement('option');
                opt.value = mm; opt.textContent = mm;
                minEl.appendChild(opt);
            }
            minEl.value = mm;
        }
        this._onDateTimeChange(idPrefix);
    },

    _onDateTimeChange(idPrefix) {
        const combinado = this._syncDateTimeFields(idPrefix);
        if (!combinado) return;
        const hidden = document.getElementById(idPrefix === 'appt' ? 'appt-start-hidden' : 'edit-start');
        if (hidden) hidden.value = combinado;
        if (idPrefix === 'appt') this._checkHoliday(combinado);
    },

    // Guarda un turno (alta o edicion) y, si el backend lo rechaza por
    // sobreturno (409), ofrece confirmar y reintenta con force=true. El
    // feriado y otros errores (404, etc.) no entran aca: siguen cortando.
    async _guardarConSobreturno(data, intentar) {
        try {
            return await intentar(data);
        } catch (err) {
            if (err.status === 409) {
                const confirmar = await UI.confirm(
                    'Sobreturno',
                    `${err.message} ¿Confirmás crear el turno igual?`
                );
                if (confirmar) return await intentar({ ...data, force: true });
            }
            throw err;
        }
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
                <div class="form-group form-group-full">
                    <label>Paciente *</label>
                    <!-- Un solo campo: se escribe y se elige ahi mismo. Antes eran
                         dos controles, un buscador arriba y un desplegable abajo, y
                         habia que bajar a "Seleccionar..." para confirmar lo que ya
                         se habia tipeado. -->
                    <div class="buscador-ficha">
                        <input type="text" id="appt-patient-search" autocomplete="off"
                               placeholder="Buscar por nombre, apellido o DNI..."
                               oninput="AgendaPage._filterPatients(this.value)"
                               onfocus="AgendaPage._filterPatients(this.value)"
                               onblur="AgendaPage._cerrarResultados()"
                               onkeydown="AgendaPage._teclaEnBuscador(event)">
                        <input type="hidden" name="patient_id" id="appt-patient-id">
                        <div id="appt-patient-results" class="buscador-resultados" hidden></div>
                    </div>
                    <div id="appt-patient-chosen" class="buscador-elegido" hidden></div>
                    <!-- Aparece recien con un paciente elegido: el registro se
                         carga sobre alguien, y hasta que no se elige no hay
                         sobre quien. -->
                    <button type="button" id="appt-odontograma" hidden
                            class="btn btn-sm btn-ghost"
                            style="margin-top:.35rem;color:var(--primary);"
                            onclick="AgendaPage._abrirOdontograma()">🦷 Cargar en el odontograma</button>
                    <button type="button" class="btn btn-sm btn-ghost" style="margin-top:.35rem;color:var(--primary);" onclick="AgendaPage._toggleNewPatient()">+ Nuevo paciente</button>
                    <div id="appt-new-patient" style="display:none;margin-top:.5rem;padding:.75rem;background:var(--slate-50);border-radius:8px;border:1px solid var(--slate-200);">
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem;">
                            <input type="text" id="np-first" placeholder="Nombre *">
                            <input type="text" id="np-last" placeholder="Apellido *">
                            <input type="text" id="np-dni" placeholder="DNI (opcional)">
                            <input type="text" id="np-phone" placeholder="Teléfono (opcional)">
                        </div>
                        <small style="color:var(--slate-500);">Solo nombre y apellido son obligatorios. El DNI y el teléfono se completan después, desde Pacientes.</small>
                        <button type="button" class="btn btn-sm btn-primary" style="margin-top:.5rem;display:block;" onclick="AgendaPage._createPatientInline()">Crear y seleccionar</button>
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
                    ${AgendaPage._dateTimeFieldsHTML('appt', defaultDateTime, 'id="appt-start-hidden" name="start_time"')}
                    <div id="appt-holiday-warning" style="display:none;margin-top:.35rem;padding:.4rem .6rem;border-radius:6px;background:#fee2e2;color:#991b1b;font-size:.82rem;"></div>
                </div>
                <div class="form-group">
                    <label>Duración (min)</label>
                    <input type="number" name="duration_minutes" value="30" min="15" step="15">
                </div>
                <div class="form-group">
                    <label>Sede${(this._locations || []).length > 0 ? ' *' : ''}</label>
                    <select name="location" ${(this._locations || []).length > 0 ? 'required' : ''}>
                        ${(this._locations || []).length === 0
                            ? '<option value="">Sin asignar</option>'
                            : (this._locations || []).map((l, i) =>
                                `<option value="${l.name}" ${i === 0 ? 'selected' : ''}>${l.name}</option>`).join('')}
                    </select>
                    ${(this._locations || []).length === 0
                        ? '<small style="color:var(--danger);">No hay sedes cargadas: revisá Configuración → Sedes.</small>' : ''}
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
        // Si hay sedes para elegir, se exige elegir una (evita turnos invisibles
        // para el bot). Si la lista vino vacía por un problema de carga, no se
        // bloquea la creación por eso: mejor un turno sin sede que ninguno.
        if ((this._locations || []).length > 0 && !data.location) return UI.toast('Elegí la sede', 'error');
        const h = this._holidayFor(data.start_time);
        if (h) return UI.toast(this._holidayMsg(h), 'error');
        // location: '' (opcion "Sin asignar") se manda como null, no como
        // string vacio -- el backend distingue NULL de '' al calcular ocupacion.
        this._pendingAppts.push({...data, duration_minutes: parseInt(data.duration_minutes) || 30, location: data.location || null});
        const listEl = document.getElementById('multi-appt-list');
        if (listEl) {
            const pat = (this._modalPatients || []).find(p => p.id === data.patient_id);
            const quien = pat ? `${pat.last_name}, ${pat.first_name}` : '?';
            listEl.innerHTML += `<div class="pending-appt-item"><span>🕐 ${data.start_time.replace('T',' ')} — ${quien} — ${data.reason || 'Sin motivo'}</span><button class="btn btn-sm btn-ghost" onclick="AgendaPage._removePending(${this._pendingAppts.length - 1})" style="color:var(--danger)">✕</button></div>`;
        }
        // Reset form time +30min. new Date("YYYY-MM-DDTHH:MM") sin zona se
        // interpreta como hora local, pero toISOString() la devuelve en UTC:
        // con eso la fecha/hora se corria segun el huso horario del navegador.
        // Se arma el string a mano para quedarse en hora local todo el tiempo.
        const [dd, hh] = data.start_time.split('T');
        const [yy, mo, da] = dd.split('-').map(Number);
        const [hr, mi] = hh.split(':').map(Number);
        const next = new Date(yy, mo - 1, da, hr, mi + 30);
        const pad = (n) => String(n).padStart(2, '0');
        const nextISO = `${next.getFullYear()}-${pad(next.getMonth()+1)}-${pad(next.getDate())}T${pad(next.getHours())}:${pad(next.getMinutes())}`;
        this._setDateTimeFields('appt', nextISO);
        UI.toast(`Turno agregado a lista (${this._pendingAppts.length})`, 'info');
    },

    _removePending(idx) {
        this._pendingAppts.splice(idx, 1);
        const items = document.querySelectorAll('.pending-appt-item');
        if (items[idx]) items[idx].remove();
    },

    // Buscador de paciente en el modal de Nuevo Turno.
    //
    // Dos cosas estaban mal. Filtraba en el navegador sobre `_modalPatients`,
    // que es lo que devolvio /clinic/patients al abrir el modal: la PRIMERA
    // pagina, 50 fichas. Con la agenda cargada el paciente buscado casi nunca
    // estaba ahi, se tipeaba el apellido y no aparecia nada. Y aunque
    // apareciera, elegirlo pedia bajar a un desplegable aparte.
    // Ahora busca el servidor y se elige en el mismo campo.
    _filterPatients(q) {
        clearTimeout(this._patientSearchTimer);
        // Debounce: sin esto sale un request por tecla.
        this._patientSearchTimer = setTimeout(
            // La coma de "Apellido, Nombre" queda en el campo despues de elegir:
            // sin sacarla, volver a enfocarlo no encontraba a nadie.
            () => this._runPatientSearch((q || '').replace(/,/g, ' ').trim()), 250);
    },

    async _runPatientSearch(q) {
        const caja = document.getElementById('appt-patient-results');
        if (!caja) return;
        // Cada busqueda lleva numero: si una respuesta lenta llega despues de
        // una mas nueva, se descarta en vez de pisar la lista buena.
        const token = (this._patientSearchToken || 0) + 1;
        this._patientSearchToken = token;

        // Si borro lo que habia escrito, tambien se suelta al paciente elegido:
        // si no, quedaba un turno a nombre de alguien que ya no se ve.
        if (!q) this._elegirPaciente(null);

        let list;
        if (!q) {
            list = this._modalPatients;
        } else {
            try {
                list = await API.getPatients(q, 200);
            } catch (e) {
                // Sin red, al menos filtrar lo que ya esta cargado: peor es
                // dejar al usuario sin ninguna opcion.
                const n = q.toLowerCase();
                list = this._modalPatients.filter(p =>
                    `${p.last_name} ${p.first_name} ${p.dni || ''}`.toLowerCase().includes(n));
            }
        }
        if (token !== this._patientSearchToken) return;

        // Lo encontrado se suma a la lista del modal: el resumen de "Agregar a
        // lista" busca el nombre ahi, y sin esto mostraba "?".
        const conocidos = new Set(this._modalPatients.map(p => p.id));
        list.forEach(p => { if (!conocidos.has(p.id)) this._modalPatients.push(p); });

        this._resultados = list;
        this._resaltado = list.length ? 0 : -1;
        this._pintarResultados(q);
    },

    _pintarResultados(q) {
        const caja = document.getElementById('appt-patient-results');
        if (!caja) return;
        const lista = this._resultados || [];

        if (lista.length === 0) {
            caja.innerHTML = q
                ? `<div class="buscador-vacio">Sin resultados para "${UI.escape(q)}". Probá con el apellido, o cargalo con "+ Nuevo paciente".</div>`
                : '<div class="buscador-vacio">No hay pacientes cargados todavía.</div>';
            caja.hidden = false;
            return;
        }

        caja.innerHTML = lista.map((p, i) => {
            const dni = (p.dni || '').startsWith('TMP-') ? 'sin DNI' : (p.dni || 'sin DNI');
            // mousedown en vez de click: el click llega despues del blur del
            // input, y para entonces la lista ya se cerro.
            return `<div class="buscador-fila${i === this._resaltado ? ' resaltada' : ''}"
                         data-i="${i}"
                         onmousedown="event.preventDefault(); AgendaPage._elegirPorIndice(${i})">
                        <span>${UI.escape(p.last_name)}, ${UI.escape(p.first_name)}</span>
                        <small>${UI.escape(dni)}</small>
                    </div>`;
        }).join('');
        caja.hidden = false;
    },

    _teclaEnBuscador(e) {
        const lista = this._resultados || [];
        const caja = document.getElementById('appt-patient-results');
        const abierta = caja && !caja.hidden && lista.length > 0;
        if (e.key === 'Escape') {
            // Con la lista abierta, Escape la cierra y no llega al modal: el
            // segundo Escape ya cierra el modal. Sin esto, querer descartar el
            // desplegable te cerraba el turno entero.
            if (abierta) e.stopPropagation();
            return this._cerrarResultados(0);
        }
        if (!abierta) return;

        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            const paso = e.key === 'ArrowDown' ? 1 : -1;
            this._resaltado = (this._resaltado + paso + lista.length) % lista.length;
            this._pintarResultados(document.getElementById('appt-patient-search').value.trim());
            const fila = caja.querySelector(`[data-i="${this._resaltado}"]`);
            if (fila) fila.scrollIntoView({block: 'nearest'});
        } else if (e.key === 'Enter') {
            // Sin esto, Enter manda el formulario con el paciente sin elegir.
            e.preventDefault();
            this._elegirPorIndice(this._resaltado);
        }
    },

    _elegirPorIndice(i) {
        const p = (this._resultados || [])[i];
        if (p) this._elegirPaciente(p);
    },

    // Fuente unica de "quien es el paciente de este turno". `null` lo suelta.
    _elegirPaciente(p) {
        const oculto = document.getElementById('appt-patient-id');
        const buscador = document.getElementById('appt-patient-search');
        const cartel = document.getElementById('appt-patient-chosen');
        if (!oculto) return;

        oculto.value = p ? p.id : '';
        if (cartel) {
            cartel.hidden = !p;
            cartel.innerHTML = p ? `✓ ${UI.escape(p.last_name)}, ${UI.escape(p.first_name)}` : '';
        }
        const botonOdo = document.getElementById('appt-odontograma');
        if (botonOdo) botonOdo.hidden = !p;
        if (p) {
            if (buscador) buscador.value = `${p.last_name}, ${p.first_name}`;
            this._cerrarResultados(0);
        }
    },

    // Abre el Registro Manual del odontograma para el paciente elegido, sin
    // salir de la carga del turno.
    //
    // El modal es uno solo en toda la app, asi que el odontograma TAPA al del
    // turno. Por eso se guarda lo que haya cargado y se repone al volver: si
    // no, abrir el odontograma costaba tener que cargar el turno de nuevo.
    _abrirOdontograma() {
        const oculto = document.getElementById('appt-patient-id');
        const paciente = (this._modalPatients || []).find(p => p.id === (oculto || {}).value);
        if (!paciente) return UI.toast('Elegí primero el paciente', 'error');

        this._guardarModalTurno(paciente);

        OdontogramPage.showEntryForm({
            patientId: paciente.id,
            titulo: `Odontograma — ${paciente.last_name}, ${paciente.first_name}`,
            alCerrar: () => AgendaPage._reponerModalTurno(),
        });
    },

    // `pacienteElegido` pisa al que estaba seleccionado: lo usa el aviso de
    // ficha repetida, donde el resultado es justamente cambiar de paciente.
    async _reponerModalTurno(pacienteElegido = null) {
        const guardado = this._turnoAMedioCargar;
        this._turnoAMedioCargar = null;
        if (!guardado) return;

        let profesionales = [];
        try { profesionales = await API.getProfessionals(); } catch (e) {}

        this._pendingAppts = guardado.pendientes;
        this._renderMultiModal(profesionales, this._modalPatients || [],
                               guardado.datos.start_time || UI.nowISO());

        const d = guardado.datos;
        const poner = (selector, valor) => {
            const el = document.querySelector(`#form-new-appointment ${selector}`);
            if (el && valor != null && valor !== '') el.value = valor;
        };
        poner('[name="professional_id"]', d.professional_id);
        poner('[name="duration_minutes"]', d.duration_minutes);
        poner('[name="location"]', d.location);
        poner('[name="reason"]', d.reason);
        this._elegirPaciente(pacienteElegido || guardado.paciente);
    },

    // Guarda lo que haya cargado en el modal de turno para poder reponerlo.
    // El modal es uno solo en toda la app: cualquier dialogo que se abra
    // encima lo destruye.
    _guardarModalTurno(paciente = null) {
        this._turnoAMedioCargar = {
            datos: UI.getFormData('form-new-appointment'),
            paciente,
            pendientes: [...(this._pendingAppts || [])],
        };
    },

    _cerrarResultados(demora = 120) {
        clearTimeout(this._cierreResultados);
        this._cierreResultados = setTimeout(() => {
            const caja = document.getElementById('appt-patient-results');
            if (caja) caja.hidden = true;
        }, demora);
    },

    _toggleNewPatient() {
        const el = document.getElementById('appt-new-patient');
        if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
    },

    async _createPatientInline() {
        const g = id => (document.getElementById(id)?.value || '').trim();
        const first = g('np-first'), last = g('np-last');
        if (!first || !last) {
            return UI.toast('Completá al menos nombre y apellido', 'error');
        }
        // DNI y teléfono opcionales: van como null, no como '' ni como un
        // "TMP-xxxx" inventado. Ese provisorio ensuciaba la columna DNI de la
        // lista de pacientes y no aportaba nada.
        const data = {
            first_name: first,
            last_name: last,
            dni: g('np-dni') || null,
            phone: g('np-phone') || null,
        };
        try {
            const p = await API.createPatient(data);
            this._modalPatients.push(p);
            this._elegirPaciente(p);
            document.getElementById('appt-new-patient').style.display = 'none';
            UI.toast('Paciente creado y seleccionado', 'success');
            return;
        } catch (e) {
            if (!e.puedeDuplicar) return UI.toast(e.message || 'Error al crear paciente', 'error');

            // Ya hay alguien con ese nombre. El dialogo ocupa el mismo modal, o
            // sea que se lleva puesto el turno a medio cargar: se guarda antes
            // y se repone despues, con el paciente que se haya decidido.
            this._guardarModalTurno();
            const decision = await UI.fichaRepetida(e, `${last}, ${first}`);

            if (decision === null) {
                await this._reponerModalTurno();
                return;
            }

            let elegido;
            if (decision === 'crear') {
                try {
                    elegido = await API.createPatient({ ...data, force: true });
                    UI.toast('Paciente creado y seleccionado', 'success');
                } catch (e2) {
                    await this._reponerModalTurno();
                    return UI.toast(e2.message || 'Error al crear paciente', 'error');
                }
            } else {
                elegido = e.yaExisten.find(x => x.id === decision);
                UI.toast('Se usó la ficha que ya estaba', 'success');
            }

            this._modalPatients.push(elegido);
            await this._reponerModalTurno(elegido);
        }
    },

    async _saveAll() {
        const formData = UI.getFormData('form-new-appointment');
        const allAppts = [...this._pendingAppts];
        if (formData.patient_id && formData.start_time) {
            allAppts.push({...formData, duration_minutes: parseInt(formData.duration_minutes) || 30, location: formData.location || null});
        }
        if (allAppts.length === 0) return UI.toast('Agregá al menos un turno', 'error');
        // Sin sede el turno queda invisible para el bot al calcular disponibilidad,
        // asi que se exige mientras haya sedes para elegir. Si la lista vino vacía
        // (falla de carga o ninguna sede activa), no se bloquea por eso.
        if ((this._locations || []).length > 0 && allAppts.some(a => !a.location)) {
            return UI.toast('Elegí la sede', 'error');
        }

        // Ningun turno de la tanda puede caer en feriado.
        for (const appt of allAppts) {
            const h = this._holidayFor(appt.start_time);
            if (h) return UI.toast(this._holidayMsg(h), 'error');
        }

        let ok = 0;
        let sobreturnos = 0;
        const errores = [];
        for (const appt of allAppts) {
            const r = await this._crearTurno(appt);
            if (r === 'ok') ok++;
            else if (r === 'sobreturno') { ok++; sobreturnos++; }
            else if (r !== 'cancelado') errores.push(r);
        }
        this._pendingAppts = [];
        UI.closeModal();
        if (errores.length) {
            UI.toast(`${ok} turno(s) creado(s). ${errores.length} con error: ${errores[0]}`, ok > 0 ? 'info' : 'error');
        } else if (ok) {
            UI.toast(`${ok} turno(s) creado(s)` +
                     (sobreturnos ? ` (${sobreturnos} como sobreturno)` : ''), 'success');
        }
        if (AgendaPage.loadAgenda) AgendaPage.loadAgenda();
    },

    // Crea un turno. Si el horario esta ocupado no se corta ahi: se pregunta.
    // El consultorio dobla horarios a proposito —encajar un paciente encima de
    // otro es parte de como trabajan—, asi que recepcion tiene que poder
    // hacerlo. Lo que no puede es pasar inadvertido: el turno queda marcado
    // como sobreturno.
    //
    // Devuelve 'ok', 'sobreturno', 'cancelado' o el texto del error.
    async _crearTurno(appt) {
        try {
            await API.createAppointment(appt);
            return 'ok';
        } catch (err) {
            if (!err.puedeSobreturno) return err.message;

            const cuando = String(appt.start_time).replace('T', ' ');
            const quiere = await UI.confirm(
                'Horario ocupado',
                `${cuando} ya está tomado.<br><br>¿Lo cargás igual como ` +
                `<strong>sobreturno</strong>? Va a quedar marcado en la agenda.`,
            );
            if (!quiere) return 'cancelado';

            try {
                await API.createAppointment({ ...appt, force: true });
                return 'sobreturno';
            } catch (err2) {
                return err2.message;
            }
        }
    },

    async saveNewAppointment() {
        const data = UI.getFormData('form-new-appointment');
        const r = await this._crearTurno(data);
        if (r === 'cancelado') return;
        if (r === 'ok' || r === 'sobreturno') {
            UI.closeModal();
            UI.toast(r === 'sobreturno' ? 'Sobreturno creado' : 'Turno creado', 'success');
            if (AgendaPage.loadAgenda) AgendaPage.loadAgenda();
        } else {
            UI.toast(r, 'error');
        }
    }
};

