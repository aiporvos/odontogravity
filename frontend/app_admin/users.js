/**
 * Users Admin Page
 */
Router.register('users', async (container) => {
    container.innerHTML = `
        <div class="page-header">
            <h1>Gestión de Usuarios</h1>
            <div class="page-header-actions">
                <button class="btn btn-primary" onclick="UsersPage.showForm()">+ Nuevo Usuario</button>
            </div>
        </div>
        <div class="card">
            <div id="users-table" class="table-container">
                <div class="loading-page"><div class="spinner"></div></div>
            </div>
        </div>
    `;
    UsersPage.loadList();
});

const UsersPage = {
    async loadList() {
        const container = document.getElementById('users-table');
        try {
            const users = await API.getUsers();
            container.innerHTML = `
                <table>
                    <thead>
                        <tr><th>Nombre</th><th>Email</th><th>Rol</th><th>Estado</th><th>Acciones</th></tr>
                    </thead>
                    <tbody>
                        ${users.map(u => `
                            <tr>
                                <td><strong>${u.full_name}</strong></td>
                                <td>${u.email}</td>
                                <td><span class="badge badge-${u.role === 'admin' ? 'confirmed' : 'pending'}">${u.role}</span></td>
                                <td>${u.is_active ? '✅ Activo' : '⛔ Inactivo'}</td>
                                <td>
                                    <button class="btn btn-sm btn-ghost" onclick="UsersPage.showForm('${u.id}', '${u.full_name}', '${u.role}', ${u.is_active})">Editar</button>
                                    <button class="btn btn-sm btn-danger" onclick="UsersPage.deleteUser('${u.id}')">✕</button>
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

    showForm(id, name = '', role = 'receptionist', active = true) {
        const isEdit = !!id;
        const body = `
            <form id="form-user" class="form-grid">
                ${!isEdit ? `
                    <div class="form-group">
                        <label>Email *</label>
                        <input type="email" name="email" required>
                    </div>
                    <div class="form-group">
                        <label>Contraseña *</label>
                        <input type="password" name="password" required minlength="6">
                    </div>
                ` : ''}
                <div class="form-group">
                    <label>Nombre Completo *</label>
                    <input type="text" name="full_name" value="${name}" required>
                </div>
                <div class="form-group">
                    <label>Rol *</label>
                    <select name="role">
                        <option value="admin" ${role==='admin'?'selected':''}>Admin</option>
                        <option value="receptionist" ${role==='receptionist'?'selected':''}>Recepcionista</option>
                        <option value="doctor" ${role==='doctor'?'selected':''}>Doctor</option>
                    </select>
                </div>
                ${isEdit ? `
                    <div class="form-group">
                        <label>Estado</label>
                        <select name="is_active">
                            <option value="true" ${active?'selected':''}>Activo</option>
                            <option value="false" ${!active?'selected':''}>Inactivo</option>
                        </select>
                    </div>
                ` : ''}
            </form>
        `;
        const footer = `
            <button class="btn btn-secondary" onclick="UI.closeModal()">Cancelar</button>
            <button class="btn btn-primary" onclick="UsersPage.save(${isEdit ? `'${id}'` : 'null'})">${isEdit ? 'Actualizar' : 'Crear'}</button>
        `;
        UI.showModal(isEdit ? 'Editar Usuario' : 'Nuevo Usuario', body, footer);
    },

    async save(id) {
        const data = UI.getFormData('form-user');
        if (data.is_active !== undefined) data.is_active = data.is_active === 'true';
        try {
            if (id) {
                await API.updateUser(id, data);
                UI.toast('Usuario actualizado', 'success');
            } else {
                await API.createUser(data);
                UI.toast('Usuario creado', 'success');
            }
            UI.closeModal();
            this.loadList();
        } catch (err) {
            UI.toast(err.message, 'error');
        }
    },

    async deleteUser(id) {
        const ok = await UI.confirm('Eliminar Usuario', '¿Eliminar este usuario?');
        if (ok) {
            try {
                await API.deleteUser(id);
                UI.toast('Usuario eliminado', 'success');
                this.loadList();
            } catch (err) { UI.toast(err.message, 'error'); }
        }
    },
};
