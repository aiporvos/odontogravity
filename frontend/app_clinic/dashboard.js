/**
 * Inicio (antes Dashboard): saludo, próximo turno y accesos directos
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

    const ahora = new Date();
    const hora = ahora.getHours();
    const saludo = hora >= 5 && hora < 13 ? 'Buen día' : hora >= 13 && hora < 20 ? 'Buenas tardes' : 'Buenas noches';
    // Primer nombre real: se saltean títulos como "Dr." o "Dra.".
    const nombre = ((API.user && API.user.full_name) || '')
        .split(/\s+/).find(p => p && !/^(dr|dra|od|lic)\.?$/i.test(p)) || '';
    const activos = todayAppointments.filter(a => a.status !== 'cancelled');
    const proximo = activos
        .filter(a => new Date(a.start_time) >= ahora)
        .sort((a, b) => new Date(a.start_time) - new Date(b.start_time))[0];
    const resumenHoy = activos.length === 0
        ? 'Hoy no hay turnos cargados.'
        : `Hoy ${activos.length === 1 ? 'hay 1 turno' : `hay ${activos.length} turnos`}${stats.pending ? `, ${stats.pending} sin confirmar` : ''}.`;
    const ic = {
        pacientes: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
        turnos: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="3"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
        pendientes: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
        hechos: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
        nuevoTurno: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="3"/><path d="M16 2v4M8 2v4M3 10h18M12 14v4M10 16h4"/></svg>',
        nuevoPaciente: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/></svg>',
        agenda: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="3"/><path d="M16 2v4M8 2v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01"/></svg>',
        odonto: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3C8.5 3 6.5 5.5 6.5 8.2c0 2.6 1 4.3 1.8 6 .8 1.8 1.2 4.3 1.7 6 .2.6 1 .6 1.2 0l.8-3 .8 3c.2.6 1 .6 1.2 0 .5-1.7.9-4.2 1.7-6 .8-1.7 1.8-3.4 1.8-6C17.5 5.5 15.5 3 12 3z"/></svg>',
    };

    container.innerHTML = `
        <section class="inicio-hero">
            <div class="inicio-hero-texto">
                <h1>${saludo}${nombre ? `, ${UI.escape(nombre)}` : ''}</h1>
                <p>${resumenHoy}</p>
            </div>
            ${proximo ? `
            <button class="inicio-proximo" onclick="AgendaPage.showAppointment('${proximo.id}')" title="Abrir el turno">
                <span class="inicio-proximo-etiqueta">Próximo turno</span>
                <span class="inicio-proximo-hora">${UI.formatTime(proximo.start_time)}</span>
                <span class="inicio-proximo-paciente">${proximo.patient ? UI.escape(`${proximo.patient.first_name} ${proximo.patient.last_name}`) : 'Sin paciente'}</span>
                <span class="inicio-proximo-detalle">${UI.escape([proximo.professional && proximo.professional.full_name, proximo.reason].filter(Boolean).join(' · '))}</span>
            </button>` : ''}
        </section>

        <div class="acciones-rapidas">
            <button class="accion-rapida destacada" onclick="AgendaPage.showNewAppointment()">
                <span class="accion-icono">${ic.nuevoTurno}</span>
                <span><strong>Nuevo turno</strong><small>Agendar a un paciente</small></span>
            </button>
            <button class="accion-rapida" onclick="PatientsPage.showForm()">
                <span class="accion-icono">${ic.nuevoPaciente}</span>
                <span><strong>Nuevo paciente</strong><small>Cargar una ficha</small></span>
            </button>
            <button class="accion-rapida" onclick="Router.navigate('agenda')">
                <span class="accion-icono">${ic.agenda}</span>
                <span><strong>Ver agenda</strong><small>Semana y turnos</small></span>
            </button>
            <button class="accion-rapida" onclick="Router.navigate('odontogram')">
                <span class="accion-icono">${ic.odonto}</span>
                <span><strong>Odontograma</strong><small>Prestaciones</small></span>
            </button>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon blue">${ic.pacientes}</div>
                <div class="stat-info">
                    <div class="stat-value">${stats.patients}</div>
                    <div class="stat-label">Pacientes registrados</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon green">${ic.turnos}</div>
                <div class="stat-info">
                    <div class="stat-value">${stats.appointments_today}</div>
                    <div class="stat-label">Turnos hoy</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon yellow">${ic.pendientes}</div>
                <div class="stat-info">
                    <div class="stat-value">${stats.pending}</div>
                    <div class="stat-label">Sin confirmar</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon red">${ic.hechos}</div>
                <div class="stat-info">
                    <div class="stat-value">${stats.completed}</div>
                    <div class="stat-label">Atendidos hoy</div>
                </div>
            </div>
        </div>

        ${toReschedule.length === 0 ? '' : `
        <div class="card card-alerta" style="margin-bottom:1.5rem;">
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
                <h2>Turnos de hoy</h2>
                <button class="btn btn-sm btn-ghost" onclick="Router.navigate('agenda')">Ir a la agenda →</button>
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
