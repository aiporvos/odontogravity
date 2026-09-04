/**
 * Patients Page - CRUD for patient records
 */
Router.register('patients', async (container) => {
    container.innerHTML = `
        <div class="page-header">
            <h1>Pacientes</h1>
            <div class="page-header-actions">
                <button class="btn btn-primary" id="btn-new-patient">+ Nuevo Paciente</button>
            </div>
        </div>
        <div class="card">
            <div style="margin-bottom:1rem;">
                <input type="text" id="patient-search" placeholder="Buscar por nombre, apellido o DNI..." 
                    style="width:100%;max-width:400px;padding:.6rem .85rem;border:1px solid var(--slate-300);border-radius:var(--radius);font-size:.9rem;">
            </div>
            <div id="patients-table" class="table-container">
                <div class="loading-page"><div class="spinner"></div></div>
            </div>
        </div>
    `;

    let debounce;
    document.getElementById('patient-search').addEventListener('input', (e) => {
        clearTimeout(debounce);
        debounce = setTimeout(() => PatientsPage.loadList(e.target.value), 300);
    });

    document.getElementById('btn-new-patient').addEventListener('click', () => PatientsPage.showForm());

    PatientsPage.loadList();
});

const PatientsPage = {
    async loadList(q = '') {
        const container = document.getElementById('patients-table');
        try {
            const patients = await API.getAllPatients(q);
            UI.tabla('patients-table', {
                filas: patients,
                vacio: 'No se encontraron pacientes',
                columnas: [
                    {titulo: 'Apellido, Nombre',
                     valor: p => `${p.last_name}, ${p.first_name}`,
                     html: p => `<strong>${UI.escape(p.last_name)}, ${UI.escape(p.first_name)}</strong>`},
                    {titulo: 'DNI', valor: p => p.dni,
                     html: p => p.dni
                        ? UI.escape(p.dni)
                        : '<span class="badge badge-cancelled" title="Falta completar el DNI cuando el paciente venga">falta DNI</span>'},
                    {titulo: 'Teléfono', valor: p => p.phone,
                     html: p => p.phone
                        ? UI.escape(p.phone)
                        : '<span class="badge badge-cancelled" title="Sin teléfono no recibe recordatorios">falta teléfono</span>'},
                    {titulo: 'Obra Social', valor: p => p.insurance_name,
                     html: p => UI.escape(p.insurance_name || '-')},
                    {titulo: 'Acciones', orden: false, valor: () => '', html: p => `
                        <button class="btn btn-sm btn-ghost" onclick="PatientsPage.showForm('${p.id}')">Editar</button>
                        <button class="btn btn-sm btn-primary" onclick="PatientsPage.viewOdontogram('${p.id}')">🦷</button>
                        <button class="btn btn-sm btn-danger" onclick="PatientsPage.deletePatient('${p.id}')">✕</button>`},
                ],
            });
        } catch (err) {
            container.innerHTML = `<div class="empty-state"><div class="empty-state-text">Error: ${err.message}</div></div>`;
        }
    },

    async showForm(id = null) {
        let patient = { first_name: '', last_name: '', dni: '', phone: '', email: '', date_of_birth: '', address: '', city: '', insurance_name: '', insurance_number: '', medical_notes: '' };
        if (id) {
            try { patient = await API.getPatient(id); } catch (e) { UI.toast(e.message, 'error'); return; }
        }

        const body = `
            <form id="form-patient" class="form-grid">
                <div class="form-group">
                    <label>Nombre *</label>
                    <input type="text" name="first_name" value="${patient.first_name}" required>
                </div>
                <div class="form-group">
                    <label>Apellido *</label>
                    <input type="text" name="last_name" value="${patient.last_name}" required>
                </div>
<!-- Solo nombre y apellido son obligatorios. Recepcion carga fichas
                     desde la agenda de papel, donde el DNI y el telefono casi nunca
                     estan anotados; exigirlos obligaba a inventarlos, y un telefono
                     inventado hace que el recordatorio le llegue a un tercero. -->
                <div class="form-group">
                    <label>DNI</label>
                    <input type="text" name="dni" value="${patient.dni && !String(patient.dni).startsWith('TMP-') ? patient.dni : ''}" ${id && patient.dni && !String(patient.dni).startsWith('TMP-') ? 'readonly' : ''} placeholder="Se completa cuando el paciente viene">
                </div>
                <div class="form-group">
                    <label>Teléfono</label>
                    <input type="text" name="phone" value="${patient.phone || ''}" placeholder="Sin teléfono no recibe recordatorios">
                </div>
                <div class="form-group">
                    <label>Email</label>
                    <input type="email" name="email" value="${patient.email || ''}">
                </div>
                <div class="form-group">
                    <label>Fecha de Nacimiento</label>
                    <input type="date" name="date_of_birth" value="${patient.date_of_birth || ''}">
                </div>
                <div class="form-group">
                    <label>Dirección</label>
                    <input type="text" name="address" value="${patient.address || ''}">
                </div>
                <div class="form-group">
                    <label>Ciudad</label>
                    <input type="text" name="city" value="${patient.city || ''}">
                </div>
                <div class="form-group">
                    <label>Obra Social</label>
                    <input type="text" name="insurance_name" value="${patient.insurance_name || ''}">
                </div>
                <div class="form-group">
                    <label>Nº Afiliado</label>
                    <input type="text" name="insurance_number" value="${patient.insurance_number || ''}">
                </div>
                <div class="form-group form-group-full">
                    <label>Notas Médicas</label>
                    <textarea name="medical_notes">${patient.medical_notes || ''}</textarea>
                </div>
            </form>
        `;
        const footer = `
            <button class="btn btn-secondary" onclick="UI.closeModal()">Cancelar</button>
            <button class="btn btn-primary" onclick="PatientsPage.savePatient(${id ? `'${id}'` : 'null'})">${id ? 'Actualizar' : 'Crear'} Paciente</button>
        `;
        UI.showModal(id ? 'Editar Paciente' : 'Nuevo Paciente', body, footer);
    },

    async savePatient(id) {
        const data = UI.getFormData('form-patient');
        if (!data.first_name || !data.last_name) {
            UI.toast('Completá nombre y apellido', 'error');
            return;
        }
        // Los campos opcionales vacíos ('') se envían como null; si no, valores
        // tipados como la fecha de nacimiento rompen la validación (error 422).
        Object.keys(data).forEach(k => { if (data[k] === '') data[k] = null; });
        try {
            if (id) {
                await API.updatePatient(id, data);
                UI.toast('Paciente actualizado', 'success');
            } else {
                await API.createPatient(data);
                UI.toast('Paciente creado', 'success');
            }
            UI.closeModal();
            PatientsPage.loadList();
        } catch (err) {
            if (!err.puedeDuplicar) return UI.toast(err.message, 'error');

            // Ya hay una ficha con ese nombre: se pregunta en vez de crear el
            // duplicado en silencio.
            const decision = await UI.fichaRepetida(
                err, `${data.last_name}, ${data.first_name}`);
            if (decision === null) return;

            if (decision !== 'crear') {
                // Abrir la que ya existe, que es lo que se queria cargar.
                PatientsPage.showForm(decision);
                return;
            }

            try {
                await API.createPatient({ ...data, force: true });
                UI.closeModal();
                UI.toast('Paciente creado', 'success');
                PatientsPage.loadList();
            } catch (err2) { UI.toast(err2.message, 'error'); }
        }
    },

    async deletePatient(id) {
        const ok = await UI.confirm('Eliminar Paciente', '¿Estás seguro? Se marcará como eliminado (soft-delete).');
        if (ok) {
            try {
                await API.deletePatient(id);
                UI.toast('Paciente eliminado', 'success');
                PatientsPage.loadList();
            } catch (err) {
                UI.toast(err.message, 'error');
            }
        }
    },

    viewOdontogram(patientId) {
        // Store patient ID and navigate to odontogram
        sessionStorage.setItem('odontogram_patient_id', patientId);
        Router.currentPage = null;
        Router.navigate('odontogram');
    },
};
