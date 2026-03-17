/**
 * Dashboard Page
 */
Router.register('dashboard', async (container) => {
    let stats = { patients: 0, appointments_today: 0, pending: 0, completed: 0 };
    let todayAppointments = [];

    try {
        const today = UI.todayISO();
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        const tomorrowISO = tomorrow.toISOString().split('T')[0];

        const [patients, appointments] = await Promise.all([
            API.getPatients(),
            API.getAppointments({ date_from: `${today}T00:00:00`, date_to: `${today}T23:59:59` }),
        ]);

        stats.patients = patients.length;
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
                <span style="color:var(--slate-500);font-size:.85rem;">📍 Dental Studio Pro</span>
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

        <div class="card">
            <div class="card-header">
                <h2>Turnos de Hoy</h2>
                <button class="btn btn-sm btn-primary" onclick="Router.navigate('agenda')">Ver Agenda</button>
            </div>
            <div class="table-container">
                ${todayAppointments.length === 0
                    ? '<div class="empty-state"><div class="empty-state-icon">📅</div><div class="empty-state-text">No hay turnos para hoy</div></div>'
                    : `<table>
                        <thead>
                            <tr>
                                <th>Hora</th>
                                <th>Paciente</th>
                                <th>Profesional</th>
                                <th>Motivo</th>
                                <th>Estado</th>
                                <th>Canal</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${todayAppointments.map(a => `
                                <tr>
                                    <td><strong>${UI.formatTime(a.start_time)}</strong></td>
                                    <td>${a.patient ? `${a.patient.last_name}, ${a.patient.first_name}` : '-'}</td>
                                    <td>${a.professional ? a.professional.full_name : '-'}</td>
                                    <td>${a.reason || '-'}</td>
                                    <td>${UI.statusBadge(a.status)}</td>
                                    <td>${UI.channelLabel(a.channel)}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>`
                }
            </div>
        </div>
    `;
});
