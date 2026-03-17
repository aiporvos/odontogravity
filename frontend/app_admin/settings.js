/**
 * Settings Admin Page
 */
Router.register('settings', async (container) => {
    let locations = [];
    let insurances = [];
    try {
        [locations, insurances] = await Promise.all([API.getLocations(), API.getInsurances()]);
    } catch (e) {}

    container.innerHTML = `
        <div class="page-header">
            <h1>Configuración</h1>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;">
            <div class="card">
                <div class="card-header">
                    <h2>📍 Sedes</h2>
                </div>
                ${locations.map(l => `
                    <div style="padding:.5rem 0;border-bottom:1px solid var(--slate-100);display:flex;justify-content:space-between;align-items:center;">
                        <div>
                            <strong>${l.name}</strong>
                            <div style="font-size:.8rem;color:var(--slate-500);">${l.address || ''}</div>
                        </div>
                        <span class="badge badge-${l.is_active ? 'confirmed' : 'cancelled'}">${l.is_active ? 'Activa' : 'Inactiva'}</span>
                    </div>
                `).join('')}
            </div>

            <div class="card">
                <div class="card-header">
                    <h2>🏥 Obras Sociales</h2>
                </div>
                ${insurances.map(i => `
                    <div style="padding:.5rem 0;border-bottom:1px solid var(--slate-100);display:flex;justify-content:space-between;align-items:center;">
                        <div>
                            <strong>${i.name}</strong>
                            <div style="font-size:.8rem;color:var(--slate-500);">Código: ${i.code || '-'}</div>
                        </div>
                        <span class="badge badge-${i.is_active ? 'confirmed' : 'cancelled'}">${i.is_active ? 'Activa' : 'Inactiva'}</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
});
