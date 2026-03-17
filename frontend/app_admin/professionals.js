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

        const body = `
            <form id="form-prof" class="form-grid">
                <div class="form-group">
                    <label>Nombre Completo *</label>
                    <input type="text" name="full_name" value="${prof.full_name}" required>
                </div>
                <div class="form-group">
                    <label>Matrícula *</label>
                    <input type="text" name="license_number" value="${prof.license_number}" required ${id ? 'readonly' : ''}>
                </div>
                <div class="form-group">
                    <label>Especialidades (separar con coma)</label>
                    <input type="text" name="specialties" value="${prof.specialties.join(', ')}" placeholder="Extracciones, Implantes">
                </div>
                <div class="form-group">
                    <label>Sedes (separar con coma)</label>
                    <input type="text" name="locations" value="${prof.locations.join(', ')}" placeholder="San Rafael, Alvear">
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

        try {
            if (id) {
                await API.updateProfessional(id, data);
                UI.toast('Profesional actualizado', 'success');
            } else {
                await API.createProfessional(data);
                UI.toast('Profesional creado', 'success');
            }
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
