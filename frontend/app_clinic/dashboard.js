/**
 * Dashboard Page
 */
Router.register('dashboard', async (container) => {
    let stats = { patients: 0, appointments_today: 0, pending: 0, completed: 0 };
    let todayAppointments = [];
    let toReschedule = [];

    try {
        const today = UI.todayISO();
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        const tomorrowISO = tomorrow.toISOString().split('T')[0];

        const [cuenta, appointments, reschedule] = await Promise.all([
            // El total lo cuenta el servidor: antes se traia la primera pagina
            // de pacientes y se mostraba su largo, o sea 50 fijo con 475 fichas.
            API.contarPatients().catch(() => ({ total: 0 })),
            API.getAppointments({ date_from: `${today}T00:00:00`, date_to: `${today}T23:59:59` }),
            API.getRescheduleList().catch(() => []),
        ]);
        toReschedule = reschedule || [];

        stats.patients = cuenta.total;
        stats.appointments_today = appointments.length;
        stats.pending = appointments.filter(a => a.status === 'pending').length;
        stats.completed = appointments.filter(a => a.status === 'completed').length;
        todayAppointments = appointments;
    } catch (err) {
        console.log('Stats loading error:', err);
    }

    container.innerHTML = `
        <div class="page-header">
            <h1>Dashboard</h1>
            <div class="page-header-actions">
                <span style="color:var(--slate-500);font-size:.85rem;">📍 Silprodent</span>
            </div>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon blue">👥</div>
                <div class="stat-info">
                    <div class="stat-value">${stats.patients}</div>
                    <div class="stat-label">Pacientes Registrados</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon green">📅</div>
                <div class="stat-info">
                    <div class="stat-value">${stats.appointments_today}</div>
                    <div class="stat-label">Turnos Hoy</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon yellow">⏳</div>
                <div class="stat-info">
                    <div class="stat-value">${stats.pending}</div>
                    <div class="stat-label">Pendientes</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon red">✅</div>
                <div class="stat-info">
                    <div class="stat-value">${stats.completed}</div>
                    <div class="stat-label">Realizados Hoy</div>
                </div>
            </div>
        </div>

        ${toReschedule.length === 0 ? '' : `
        <div class="card" style="border:2px solid var(--danger);margin-bottom:1.5rem;">
            <div class="card-header">
                <h2 style="color:var(--danger);">⚠️ Turnos a reprogramar (${toReschedule.length})</h2>
            </div>
            <p style="font-size:.85rem;color:var(--slate-500);margin-bottom:.75rem;">
                Estos turnos caen en un día en que el profesional está ausente. Reprogramalos.
            </p>
            <div class="table-container" id="tabla-reprogramar"></div>
            </div>
        </div>
        `}

        <div class="card">
            <div class="card-header">
                <h2>Turnos de Hoy</h2>
                <button class="btn btn-sm btn-primary" onclick="Router.navigate('agenda')">Ver Agenda</button>
            </div>
            <div class="table-container" id="tabla-hoy"></div>
            </div>
        </div>
    `;

    // Las tablas se dibujan despues del innerHTML: UI.tabla necesita el
    // contenedor ya en el documento, y de paso quedan con orden y paginado.
    if (toReschedule.length) {
        UI.tabla('tabla-reprogramar', {
            filas: toReschedule,
            porPagina: 10,
            vacio: 'No hay turnos para reprogramar',
            columnas: [
                {titulo: 'Fecha/Hora', valor: a => new Date(a.start_time),
                 html: a => `<strong>${UI.formatDateTime(a.start_time)}</strong>`},
                {titulo: 'Paciente',
                 valor: a => a.patient ? `${a.patient.last_name}, ${a.patient.first_name}` : ''},
                {titulo: 'Profesional', valor: a => a.professional ? a.professional.full_name : ''},
                {titulo: 'Motivo', valor: a => a.reason},
                {titulo: '', orden: false, valor: () => '', html: a =>
                    `<button class="btn btn-sm btn-primary" onclick="AgendaPage.showAppointment('${a.id}')">Reprogramar</button>`},
            ],
        });
    }

    UI.tabla('tabla-hoy', {
        filas: todayAppointments,
        porPagina: 15,
        vacio: 'No hay turnos para hoy',
        columnas: [
            {titulo: 'Hora', valor: a => new Date(a.start_time),
             html: a => `<strong>${UI.formatTime(a.start_time)}</strong>`},
            {titulo: 'Paciente',
             valor: a => a.patient ? `${a.patient.last_name}, ${a.patient.first_name}` : ''},
            {titulo: 'Profesional', valor: a => a.professional ? a.professional.full_name : ''},
            {titulo: 'Motivo', valor: a => a.reason},
            {titulo: 'Estado', valor: a => a.status, html: a => UI.statusBadge(a.status)},
            {titulo: 'Canal', valor: a => a.channel, html: a => UI.channelLabel(a.channel)},
        ],
    });
});
