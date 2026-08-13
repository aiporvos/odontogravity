/**
 * Professionals Admin Page
 */
Router.register('professionals', async (container) => {
    container.innerHTML = `
        <div class="page-header">
            <h1>Profesionales</h1>
            <div class="page-header-actions">
                <button class="btn btn-primary" onclick="ProfessionalsPage.showForm()">+ Nuevo Profesional</button>
            </div>
        </div>
        <div class="card">
            <div id="profs-table" class="table-container">
                <div class="loading-page"><div class="spinner"></div></div>
            </div>
        </div>
    `;
    ProfessionalsPage.loadList();
});

const ProfessionalsPage = {
    _scheduleClinic: [],
    _scheduleChecked: new Set(),

    // Grilla de dias x franjas. Se listan solo las franjas que la clinica
    // realmente tiene abiertas ese dia (no "manana/tarde" fijos): si un dia
    // tiene una sola franja cargada en Horarios, ese es el unico casillero.
    _renderScheduleGrid() {
        const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];
        const porDia = {};
        (this._scheduleClinic || []).forEach(b => {
            (porDia[b.weekday] = porDia[b.weekday] || []).push(b);
        });
        const dias = Object.keys(porDia).map(Number).sort((a, b) => a - b);
        if (dias.length === 0) {
            return `<small style="color:var(--slate-500);">Cargá primero el horario general de la clínica en la página de Horarios.</small>`;
        }
        return `
            <div style="display:flex;flex-direction:column;gap:.5rem;padding:.75rem;background:var(--slate-50);border-radius:8px;border:1px solid var(--slate-200);">
                ${dias.map(wd => {
                    const bloques = [...porDia[wd]].sort((a, b) => (a.start_time || '').localeCompare(b.start_time || ''));
                    return `
                        <div style="display:flex;align-items:center;gap:.9rem;flex-wrap:wrap;">
                            <strong style="min-width:85px;font-size:.85rem;">${DIAS[wd]}</strong>
                            ${bloques.map(b => {
                                const ini = (b.start_time || '').slice(0, 5), fin = (b.end_time || '').slice(0, 5);
                                const key = `${wd}|${ini}|${fin}`;
                                const checked = this._scheduleChecked.has(key);
                                return `
                                    <label style="display:flex;align-items:center;gap:.3rem;font-size:.85rem;font-weight:400;cursor:pointer;margin:0;">
                                        <input type="checkbox" ${checked ? 'checked' : ''}
                                            onchange="ProfessionalsPage._toggleSchedule('${key}', this.checked)">
                                        ${ini}–${fin}
                                    </label>
                                `;
                            }).join('')}
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    },

    _toggleSchedule(key, checked) {
        if (checked) this._scheduleChecked.add(key);
        else this._scheduleChecked.delete(key);
    },

    async loadList() {
        const container = document.getElementById('profs-table');
        try {
            const profs = await API.getAdminProfessionals();
            container.innerHTML = `
                <table>
                    <thead>
                        <tr><th>Nombre</th><th>Matrícula</th><th>Especialidades</th><th>Sedes</th><th>Estado</th><th>Acciones</th></tr>
                    </thead>
                    <tbody>
                        ${profs.map(p => `
                            <tr>
                                <td><strong>${p.full_name}</strong></td>
                                <td>${p.license_number}</td>
                                <td>${p.specialties.join(', ')}</td>
                                <td>${p.locations.join(', ')}</td>
                                <td>${p.is_active ? '✅' : '⛔'}</td>
                                <td>
                                    <button class="btn btn-sm btn-ghost" onclick="ProfessionalsPage.showForm('${p.id}')">Editar</button>
                                    <button class="btn btn-sm btn-danger" onclick="ProfessionalsPage.deleteProfessional('${p.id}')">✕</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
        } catch (err) {
            container.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error: ${err.message}</div></div>`;
        }
    },

    async showForm(id = null) {
        let prof = { full_name: '', license_number: '', specialties: [], locations: [], phone: '', email: '', notes: '' };
        if (id) {
            try {
                const profs = await API.getAdminProfessionals();
                prof = profs.find(p => p.id === id) || prof;
            } catch (e) {}
        }

        // Días y franjas en que atiende. Se muestran solo las franjas que la
        // clínica realmente tiene abiertas cada día (no "mañana/tarde" fijos a
        // mano): si el miércoles la clínica solo abre a la mañana, ese es el
        // único casillero que aparece para el miércoles.
        let clinicSchedule = [], profSchedule = [];
        try {
            const tareas = [API.getSchedule()];
            if (id) tareas.push(API.getProfessionalSchedule(id));
            const resultados = await Promise.all(tareas);
            clinicSchedule = resultados[0] || [];
            profSchedule = id ? (resultados[1] || []) : [];
        } catch (e) {}
        this._scheduleClinic = clinicSchedule;
        this._scheduleChecked = new Set(
            profSchedule.map(b => `${b.weekday}|${(b.start_time||'').slice(0,5)}|${(b.end_time||'').slice(0,5)}`)
        );

        const body = `
            <form id="form-prof" class="form-grid">
                <div class="form-group">
                    <label>Nombre Completo *</label>
                    <input type="text" name="full_name" value="${prof.full_name}" required>
                </div>
                <div class="form-group">
                    <label>Matrícula *</label>
                    <input type="text" name="license_number" value="${prof.license_number}" required>
                </div>
                <div class="form-group form-group-full">
                    <label>Especialidades (separar con coma)</label>
                    <input type="text" name="specialties" value="${(prof.specialties || []).join(', ')}" placeholder="Cirugía, Extracción, Limpieza, Arreglos">
                    <small>Con esto el bot decide a quién asignarle cada turno: compara el motivo
                    que dice el paciente contra estas especialidades. Si una la atienden los dos,
                    cargala en ambos. Sin acentos ni plurales exactos: "extracción" y "extracciones" se toman igual.</small>
                </div>
                <div class="form-group">
                    <label>Sedes (separar con coma)</label>
                    <input type="text" name="locations" value="${(prof.locations || []).join(', ')}" placeholder="San Rafael, Alvear">
                </div>
                <div class="form-group">
                    <label>Teléfono</label>
                    <input type="text" name="phone" value="${prof.phone || ''}">
                </div>
                <div class="form-group">
                    <label>Email</label>
                    <input type="email" name="email" value="${prof.email || ''}">
                </div>
                <div class="form-group form-group-full">
                    <label>Días y horarios que atiende</label>
                    <div id="prof-schedule-grid">${ProfessionalsPage._renderScheduleGrid()}</div>
                    <small>Si no se marca ningún casillero, el bot lo ofrece en cualquier horario
                    general de la clínica (para no dejar sin turnos a un profesional recién
                    cargado). Marcando al menos uno, sólo se ofrece en los horarios tildados.</small>
                </div>
                <div class="form-group form-group-full">
                    <label>Notas</label>
                    <textarea name="notes">${prof.notes || ''}</textarea>
                </div>
            </form>
        `;
        const footer = `
            <button class="btn btn-secondary" onclick="UI.closeModal()">Cancelar</button>
            <button class="btn btn-primary" onclick="ProfessionalsPage.save(${id ? `'${id}'` : 'null'})">${id ? 'Actualizar' : 'Crear'}</button>
        `;
        UI.showModal(id ? 'Editar Profesional' : 'Nuevo Profesional', body, footer);
    },

    async save(id) {
        const data = UI.getFormData('form-prof');
        // Parse comma-separated arrays
        data.specialties = data.specialties ? data.specialties.split(',').map(s => s.trim()).filter(Boolean) : [];
        data.locations = data.locations ? data.locations.split(',').map(s => s.trim()).filter(Boolean) : [];

        // Dias/franjas tildados -> bloques para el endpoint de horario propio.
        // No viaja en `data`: los checkboxes de la grilla no tienen name, para
        // no mezclarse con getFormData.
        const scheduleBlocks = [...this._scheduleChecked].map(key => {
            const [weekday, start_time, end_time] = key.split('|');
            return { weekday: Number(weekday), start_time, end_time };
        });

        try {
            let profId = id;
            if (id) {
                await API.updateProfessional(id, data);
                UI.toast('Profesional actualizado', 'success');
            } else {
                const creado = await API.createProfessional(data);
                profId = creado.id;
                UI.toast('Profesional creado', 'success');
            }
            // Se guarda aparte porque es un endpoint propio (no es un campo mas
            // del profesional): reemplaza toda la grilla por la tildada ahora.
            await API.saveProfessionalSchedule(profId, scheduleBlocks);
            UI.closeModal();
            this.loadList();
        } catch (err) {
            UI.toast(err.message, 'error');
        }
    },

    async deleteProfessional(id) {
        const ok = await UI.confirm('Eliminar Profesional', '¿Eliminar este profesional?');
        if (ok) {
            try {
                await API.deleteProfessional(id);
                UI.toast('Profesional eliminado', 'success');
                this.loadList();
            } catch (err) { UI.toast(err.message, 'error'); }
        }
    },
};
