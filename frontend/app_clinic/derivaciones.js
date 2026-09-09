/**
 * Derivaciones — lo que el bot no pudo resolver y espera a una persona.
 *
 * Antes esto no existía: el bot le decía al paciente "dejé la consulta para que
 * la revisen" y lo único que pasaba era que se callaba treinta minutos. Una
 * paciente pidió cancelar su turno del día siguiente, el bot no pudo
 * identificarla y nadie se enteró. El turno siguió en la agenda.
 */
const MOTIVOS = {
    identidad: { texto: 'No se pudo identificar', clase: 'badge-pending' },
    pedido_de_persona: { texto: 'Pidió hablar con alguien', clase: 'badge-confirmed' },
    clinico: { texto: 'Molestia o dolor', clase: 'badge-cancelled' },
    dato_faltante: { texto: 'Falta un dato', clase: 'badge-pending' },
    otro: { texto: 'Otro', clase: 'badge-confirmed' },
};

Router.register('derivaciones', async (container) => {
    container.innerHTML = `
        <div class="page-header">
            <h1>Derivaciones</h1>
            <div class="page-header-actions">
                <label style="font-size:.85rem;color:var(--slate-500);display:flex;align-items:center;gap:.4rem;">
                    <input type="checkbox" id="ver-resueltas"> Ver también las resueltas
                </label>
            </div>
        </div>
        <div class="card">
            <p style="font-size:.85rem;color:var(--slate-500);margin-bottom:.75rem;">
                Conversaciones que el asistente no pudo resolver solo. Los datos que
                el paciente ya dio están acá: no hace falta volver a pedírselos.
            </p>
            <div id="derivaciones-tabla"><div class="loading-page"><div class="spinner"></div></div></div>
        </div>`;

    document.getElementById('ver-resueltas').addEventListener('change', (e) => {
        DerivacionesPage.cargar(e.target.checked);
    });
    DerivacionesPage.cargar(false);
});

const DerivacionesPage = {
    async cargar(incluirResueltas = false) {
        try {
            const filas = await API.getDerivaciones(incluirResueltas);
            UI.tabla('derivaciones-tabla', {
                filas,
                porPagina: 20,
                vacio: incluirResueltas
                    ? 'No hay derivaciones registradas'
                    : 'No hay nada esperando a recepción 👌',
                filaAttrs: d => d.estado === 'resuelta' ? 'style="opacity:.55"' : '',
                columnas: [
                    // Se ordena por la fecha real, no por el texto.
                    {titulo: 'Cuándo', valor: d => new Date(d.created_at),
                     html: d => UI.formatDateTime(d.created_at)},
                    {titulo: 'Teléfono', valor: d => d.telefono,
                     html: d => d.telefono
                        ? `<a href="https://wa.me/${UI.escape(d.telefono)}" target="_blank" rel="noopener">${UI.escape(d.telefono)}</a>`
                        : '—'},
                    {titulo: 'Motivo', valor: d => (MOTIVOS[d.motivo] || {}).texto || d.motivo,
                     html: d => {
                        const m = MOTIVOS[d.motivo] || MOTIVOS.otro;
                        return `<span class="badge ${m.clase}">${m.texto}</span>`;
                     }},
                    {titulo: 'Qué necesita', valor: d => d.resumen,
                     html: d => `<div>${UI.escape(d.resumen)}</div>` + (d.datos_aportados
                        ? `<div style="font-size:.8rem;color:var(--slate-500);margin-top:.2rem;">
                             Ya dio: ${UI.escape(d.datos_aportados)}</div>`
                        : '')},
                    {titulo: 'Estado', valor: d => d.estado,
                     html: d => d.estado === 'resuelta'
                        ? `<span class="badge badge-completed">Resuelta</span>` +
                          (d.resuelta_por ? `<div style="font-size:.75rem;color:var(--slate-500);">${UI.escape(d.resuelta_por)}</div>` : '')
                        : '<span class="badge badge-pending">Pendiente</span>'},
                    {titulo: '', orden: false, valor: () => '',
                     html: d => d.estado === 'resuelta' ? '' :
                        `<button class="btn btn-sm btn-primary" onclick="DerivacionesPage.resolver('${d.id}')">Resolver</button>`},
                ],
            });
            this.actualizarBadge(filas);
        } catch (err) {
            document.getElementById('derivaciones-tabla').innerHTML =
                `<div class="empty-state"><div class="empty-state-text">Error: ${UI.escape(err.message)}</div></div>`;
        }
    },

    async resolver(id) {
        const ok = await UI.confirm(
            'Resolver derivación',
            '¿La atendiste? Se saca de la lista de pendientes.');
        if (!ok) return;
        try {
            await API.resolverDerivacion(id, { por: (API.user || {}).email || null });
            UI.toast('Derivación resuelta', 'success');
            this.cargar(document.getElementById('ver-resueltas')?.checked || false);
        } catch (err) { UI.toast(err.message, 'error'); }
    },

    actualizarBadge(filas) {
        const badge = document.getElementById('badge-derivaciones');
        if (!badge) return;
        const pendientes = (filas || []).filter(d => d.estado === 'pendiente').length;
        badge.textContent = pendientes || '';
        badge.style.display = pendientes ? '' : 'none';
    },

    // El contador del menú se actualiza aunque no estés en la pantalla: si no,
    // nadie se entera de que hay alguien esperando.
    async revisarPendientes() {
        try {
            this.actualizarBadge(await API.getDerivaciones(false));
        } catch (e) { /* sin conexión: el contador espera al próximo ciclo */ }
    },
};
