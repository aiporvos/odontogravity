/**
 * Settings Admin Page
 */
Router.register('settings', async (container) => {
    // ── Vista por rol ──────────────────────────────────────
    // El personal de recepción (no admin) ve SOLO el encendido/apagado del bot
    // y los números de notificación. Nada de API keys ni proveedores de IA.
    const isAdmin = API.user?.role === 'admin';
    if (!isAdmin) {
        let s = {}, recInsurances = [];
        try { [s, recInsurances] = await Promise.all([API.getBotSettings(), API.getInsurances()]); } catch (e) {}
        container.innerHTML = `
            <div class="page-header"><h1>Configuración</h1></div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;align-items:start;">
            <div class="card">
                <div class="card-header"><h2>🤖 Bot de WhatsApp</h2></div>
                <form id="form-bot" style="display:flex;flex-direction:column;gap:1.5rem;padding-top:.5rem;">
                    <div class="form-group" style="margin-bottom:0; display:flex; align-items:center; gap:1rem; padding:1rem; background:var(--bg-surface); border:2px solid var(--border-color); box-shadow:var(--shadow-sm); border-radius:var(--radius-md);">
                        <label style="margin:0; font-weight:700;">🤖 Estado del Bot (IA)</label>
                        <select name="BOT_IS_ACTIVE" class="form-control" style="width:auto; margin:0; cursor:pointer; border:2px solid var(--border-color);">
                            <option value="true" ${s.BOT_IS_ACTIVE !== 'false' ? 'selected' : ''}>✅ Activo (Responde Automáticamente)</option>
                            <option value="false" ${s.BOT_IS_ACTIVE === 'false' ? 'selected' : ''}>⏸️ Pausado (Apagado)</option>
                        </select>
                    </div>
                    <div style="background:var(--slate-50); padding:1rem; border-radius:8px; border:1px solid var(--slate-200);">
                        <h4 style="margin-bottom:.8rem;">Notificaciones de WhatsApp</h4>
                        <div class="form-group">
                            <label>Números para Notificar Cancelaciones</label>
                            <input type="text" name="ADMIN_NOTIFY_NUMBERS" value="${s.ADMIN_NOTIFY_NUMBERS || ''}" placeholder="Ej: 549112345678,549112345679">
                            <small>Separados por coma. Ejemplo: 5492604123456</small>
                        </div>
                        <div class="form-group">
                            <label>Horas previas para Recordatorio</label>
                            <input type="number" name="REMINDER_HOURS_BEFORE" value="${s.REMINDER_HOURS_BEFORE || '24'}" placeholder="24">
                            <small>Cuántas horas antes del turno se envía el recordatorio.</small>
                        </div>
                    </div>
                    <button type="button" class="btn btn-primary" onclick="SettingsPage.saveBotSettings()">Guardar</button>
                </form>
            </div>

            <div class="card">
                <div class="card-header" style="justify-content:space-between;display:flex;align-items:center;">
                    <h2>🏥 Obras Sociales</h2>
                    <button class="btn btn-sm btn-primary" onclick="SettingsPage.showInsuranceForm()">+ Nueva</button>
                </div>
                ${recInsurances.map(i => `
                    <div style="padding:.5rem 0;border-bottom:1px solid var(--slate-100);display:flex;justify-content:space-between;align-items:center;">
                        <div>
                            <strong>${i.name}</strong>
                            <div style="font-size:.8rem;color:var(--slate-500);">Código: ${i.code || '-'}</div>
                        </div>
                        <div style="display:flex;gap:.5rem;align-items:center;">
                            <span class="badge badge-${i.is_active ? 'confirmed' : 'cancelled'}">${i.is_active ? 'Activa' : 'Inactiva'}</span>
                            <button class="btn btn-icon text-primary" onclick="SettingsPage.showInsuranceForm('${i.id}', '${(i.name||'').replace(/'/g, "\\'")}', '${(i.code||'').replace(/'/g, "\\'")}', ${i.is_active})">✏️</button>
                            <button class="btn btn-icon text-red" onclick="SettingsPage.deleteInsurance('${i.id}')">🗑️</button>
                        </div>
                    </div>
                `).join('')}
            </div>
            </div>
        `;
        return;
    }

    let locations = [];
    let insurances = [];
    let configs = [];
    try {
        [locations, insurances, configs] = await Promise.all([
            API.getLocations(), 
            API.getInsurances(),
            API.getConfigs()
        ]);
    } catch (e) {
        // Antes esto se tragaba el error y se seguía renderizando el formulario
        // con TODOS los campos vacíos. Un click en "Guardar Todo" escribía ""
        // encima de cada clave y borraba las API Keys. Mejor no mostrar el form.
        container.innerHTML = `
            <div class="page-header"><h1>Configuración</h1></div>
            <div class="card">
                <div class="empty-state">
                    <div class="empty-state-icon">⚠️</div>
                    <div class="empty-state-text">
                        No se pudo cargar la configuración: ${e.message || 'error de red'}.<br>
                        No se muestra el formulario para no sobrescribir los datos guardados con valores vacíos.
                    </div>
                    <button class="btn btn-primary" style="margin-top:1rem;" onclick="Router.currentPage=null;Router.navigate('settings')">Reintentar</button>
                </div>
            </div>`;
        return;
    }

    const getConfig = (key) => configs.find(c => c.key === key)?.value || '';

    container.innerHTML = `
        <div class="page-header">
            <h1>Configuración</h1>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;">
            <!-- Locations & Insurances -->
            <div style="display:flex;flex-direction:column;gap:1.5rem;">
                <div class="card">
                    <div class="card-header" style="justify-content:space-between;display:flex;align-items:center;">
                        <h2>📍 Sedes</h2>
                        <button class="btn btn-sm btn-primary" onclick="SettingsPage.showLocationForm()">+ Nueva</button>
                    </div>
                    ${locations.map(l => `
                        <div style="padding:.5rem 0;border-bottom:1px solid var(--slate-100);display:flex;justify-content:space-between;align-items:center;">
                            <div>
                                <strong>${l.name}</strong>
                                <div style="font-size:.8rem;color:var(--slate-500);">${l.address || ''}</div>
                            </div>
                            <div style="display:flex;gap:.5rem;align-items:center;">
                                <span class="badge badge-${l.is_active ? 'confirmed' : 'cancelled'}">${l.is_active ? 'Activa' : 'Inactiva'}</span>
                                <button class="btn btn-icon text-red" onclick="SettingsPage.deleteLocation('${l.id}')">🗑️</button>
                            </div>
                        </div>
                    `).join('')}
                </div>

                <div class="card">
                    <div class="card-header" style="justify-content:space-between;display:flex;align-items:center;">
                        <h2>🏥 Obras Sociales</h2>
                        <button class="btn btn-sm btn-primary" onclick="SettingsPage.showInsuranceForm()">+ Nueva</button>
                    </div>
                    ${insurances.map(i => `
                        <div style="padding:.5rem 0;border-bottom:1px solid var(--slate-100);display:flex;justify-content:space-between;align-items:center;">
                            <div>
                                <strong>${i.name}</strong>
                                <div style="font-size:.8rem;color:var(--slate-500);">Código: ${i.code || '-'}</div>
                            </div>
                            <div style="display:flex;gap:.5rem;align-items:center;">
                                <span class="badge badge-${i.is_active ? 'confirmed' : 'cancelled'}">${i.is_active ? 'Activa' : 'Inactiva'}</span>
                                <button class="btn btn-icon text-primary" onclick="SettingsPage.showInsuranceForm('${i.id}', '${(i.name||'').replace(/'/g, "\\'")}', '${(i.code||'').replace(/'/g, "\\'")}', ${i.is_active})">✏️</button>
                                <button class="btn btn-icon text-red" onclick="SettingsPage.deleteInsurance('${i.id}')">🗑️</button>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>

            <!-- Bot & AI Config -->
            <div class="card">
                <div class="card-header">
                    <h2>🤖 Integraciones (Chatbot)</h2>
                </div>
                <form id="form-config" style="display:flex;flex-direction:column;gap:1.5rem;padding-top:.5rem;">
                    <div style="background:var(--slate-50); padding:1rem; border-radius:8px; border:1px solid var(--slate-200);">
                        <h4 style="margin-bottom:.5rem;">Prioridades de Inteligencia Artificial (Fallback en cascada)</h4>
                        <p style="font-size:0.85rem; color:var(--slate-500); margin-bottom:1rem;">
                            El bot intentará responder usando el proveedor de la Prioridad 1. Si este falla (ej: error de red, límite de saldo o modelo incorrecto), pasará automáticamente a la Prioridad 2, y luego a la 3. Si todos fallan, enviará un mensaje de disculpas pidiendo contacto humano.
                        </p>
                        
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
                            <div class="form-group">
                                <label style="font-weight:700; color:var(--primary-600);">🥇 Prioridad 1 (Principal)</label>
                                <select name="AI_PROVIDER" class="form-control" style="border: 2px solid var(--primary-200);">
                                    <option value="openai" ${getConfig('AI_PROVIDER') === 'openai' ? 'selected' : ''}>OpenAI</option>
                                    <option value="openrouter" ${getConfig('AI_PROVIDER') === 'openrouter' ? 'selected' : ''}>OpenRouter</option>
                                    <option value="groq" ${getConfig('AI_PROVIDER') === 'groq' ? 'selected' : ''}>Groq</option>
                                </select>
                            </div>
                            
                            <div class="form-group">
                                <label style="font-weight:700; color:var(--slate-600);">🥈 Prioridad 2 (Respaldo)</label>
                                <select name="AI_PROVIDER_2" class="form-control">
                                    <option value="none" ${(!getConfig('AI_PROVIDER_2') || getConfig('AI_PROVIDER_2') === 'none') ? 'selected' : ''}>Ninguno</option>
                                    <option value="openai" ${getConfig('AI_PROVIDER_2') === 'openai' ? 'selected' : ''}>OpenAI</option>
                                    <option value="openrouter" ${getConfig('AI_PROVIDER_2') === 'openrouter' ? 'selected' : ''}>OpenRouter</option>
                                    <option value="groq" ${getConfig('AI_PROVIDER_2') === 'groq' ? 'selected' : ''}>Groq</option>
                                </select>
                            </div>
                            
                            <div class="form-group">
                                <label style="font-weight:700; color:var(--slate-600);">🥉 Prioridad 3 (Emergencia)</label>
                                <select name="AI_PROVIDER_3" class="form-control">
                                    <option value="none" ${(!getConfig('AI_PROVIDER_3') || getConfig('AI_PROVIDER_3') === 'none') ? 'selected' : ''}>Ninguno</option>
                                    <option value="openai" ${getConfig('AI_PROVIDER_3') === 'openai' ? 'selected' : ''}>OpenAI</option>
                                    <option value="openrouter" ${getConfig('AI_PROVIDER_3') === 'openrouter' ? 'selected' : ''}>OpenRouter</option>
                                    <option value="groq" ${getConfig('AI_PROVIDER_3') === 'groq' ? 'selected' : ''}>Groq</option>
                                </select>
                            </div>
                        </div>
                    </div>

                    <div style="background:var(--slate-50); padding:1rem; border-radius:8px; border:1px solid var(--slate-200);">
                        <h4 style="margin-bottom:.8rem;">OpenAI Config</h4>
                        <div class="form-group">
                            <label>Modelo</label>
                            <input type="text" name="OPENAI_MODEL" value="${getConfig('OPENAI_MODEL') || 'gpt-4o-mini'}" placeholder="gpt-4o-mini">
                        </div>
                        <div class="form-group">
                            <label>API Key</label>
                            <input type="password" name="OPENAI_API_KEY" value="${getConfig('OPENAI_API_KEY')}" placeholder="sk-...">
                        </div>
                    </div>

                    <div style="background:var(--slate-50); padding:1rem; border-radius:8px; border:1px solid var(--slate-200);">
                        <h4 style="margin-bottom:.8rem;">OpenRouter Config</h4>
                        <div class="form-group">
                            <label>Modelo</label>
                            <input type="text" name="OPENROUTER_MODEL" value="${getConfig('OPENROUTER_MODEL') || 'google/gemini-flash-1.5'}" placeholder="google/gemini-flash-1.5">
                        </div>
                        <div class="form-group">
                            <label>API Key</label>
                            <input type="password" name="OPENROUTER_API_KEY" value="${getConfig('OPENROUTER_API_KEY')}" placeholder="sk-or-v1-...">
                        </div>
                    </div>

                    <div style="background:var(--slate-50); padding:1rem; border-radius:8px; border:1px solid var(--slate-200);">
                        <h4 style="margin-bottom:.8rem;">Groq Config</h4>
                        <div class="form-group">
                            <label>Modelo</label>
                            <input type="text" name="GROQ_MODEL" value="${getConfig('GROQ_MODEL') || 'llama-3.1-70b-versatile'}" placeholder="llama-3.1-70b-versatile">
                        </div>
                        <div class="form-group">
                            <label>API Key</label>
                            <input type="password" name="GROQ_API_KEY" value="${getConfig('GROQ_API_KEY')}" placeholder="gsk_...">
                        </div>
                    </div>

                    <div class="form-group">
                        <label>Telegram Bot Token</label>
                        <input type="password" name="TELEGRAM_BOT_TOKEN" value="${getConfig('TELEGRAM_BOT_TOKEN')}" placeholder="123456:ABC-DEF...">
                    </div>
                    
                    <div class="form-group">
                        <label>Webhook URL (Dokploy)</label>
                        <input type="text" name="TELEGRAM_WEBHOOK_URL" value="${getConfig('TELEGRAM_WEBHOOK_URL')}" placeholder="https://tu-dominio.com/webhook">
                    </div>

                    <div style="background:var(--slate-50); padding:1rem; border-radius:8px; border:1px solid var(--slate-200);">
                        <h4 style="margin-bottom:.8rem;">📱 WhatsApp (YCloud API) & Bot</h4>
                        <p style="font-size:0.85rem; color:var(--slate-500); margin-bottom:1rem;">
                            Configuración para enviar y recibir mensajes de WhatsApp a través de YCloud. Obtené tu API Key desde el <a href="https://dashboard.ycloud.com" target="_blank">panel de YCloud</a>.
                        </p>
                        
                        <div class="form-group" style="margin-bottom: 1.5rem; display: flex; align-items: center; gap: 1rem; padding: 1rem; background: var(--bg-surface); border: 2px solid var(--border-color); box-shadow: var(--shadow-sm); border-radius: var(--radius-md);">
                            <label style="margin: 0; font-weight: 700;">🤖 Estado del Bot (IA)</label>
                            <select name="BOT_IS_ACTIVE" class="form-control" style="width: auto; margin: 0; cursor: pointer; border: 2px solid var(--border-color);">
                                <option value="true" ${getConfig('BOT_IS_ACTIVE') !== 'false' ? 'selected' : ''}>✅ Activo (Responde Automáticamente)</option>
                                <option value="false" ${getConfig('BOT_IS_ACTIVE') === 'false' ? 'selected' : ''}>⏸️ Pausado (Apagado)</option>
                            </select>
                        </div>

                        <div class="form-group">
                            <label>YCloud API Key</label>
                            <input type="password" name="YCLOUD_API_KEY" value="${getConfig('YCLOUD_API_KEY')}" placeholder="Tu API Key de YCloud">
                        </div>
                        <div class="form-group">
                            <label>Número de WhatsApp (con código de país)</label>
                            <input type="text" name="YCLOUD_FROM_PHONE" value="${getConfig('YCLOUD_FROM_PHONE')}" placeholder="Ej: 549341xxxxxxx">
                            <small>El número registrado en YCloud, sin el +. Ejemplo: 549341xxxxxxx</small>
                        </div>
                    </div>

                    <div style="background:var(--slate-50); padding:1rem; border-radius:8px; border:1px solid var(--slate-200);">
                        <h4 style="margin-bottom:.8rem;">🪑 Agenda</h4>
                        <div class="form-group">
                            <label>Sillones por sede</label>
                            <input type="number" name="CHAIRS_PER_LOCATION" min="1" step="1" value="${getConfig('CHAIRS_PER_LOCATION') || '1'}" placeholder="1">
                            <small>Cuántos turnos pueden superponerse en la misma sede. Con 1, cualquier horario ya tomado deja de ofrecerse.</small>
                        </div>
                    </div>

                    <div style="background:var(--slate-50); padding:1rem; border-radius:8px; border:1px solid var(--slate-200);">
                        <h4 style="margin-bottom:.8rem;">Configuración de Recordatorios (WhatsApp)</h4>
                        <div class="form-group">
                            <label>Números para Notificar Cancelaciones</label>
                            <input type="text" name="ADMIN_NOTIFY_NUMBERS" value="${getConfig('ADMIN_NOTIFY_NUMBERS')}" placeholder="Ej: 549112345678,549112345679">
                            <small>Separados por coma. Ejemplo: 5492604123456</small>
                        </div>
                        <div class="form-group">
                            <label>Horas previas para Recordatorio</label>
                            <input type="number" name="REMINDER_HOURS_BEFORE" value="${getConfig('REMINDER_HOURS_BEFORE') || '24'}" placeholder="24">
                            <small>Cuántas horas antes del turno se envía el recordatorio por WhatsApp.</small>
                        </div>
                    </div>

                    <button type="button" class="btn btn-primary" onclick="SettingsPage.saveConfigs()">Guardar Todo</button>
                </form>
            </div>
        </div>
    `;
});

window.SettingsPage = {
    async saveBotSettings() {
        const form = document.getElementById('form-bot');
        const data = {};
        form.querySelectorAll('input, select').forEach(el => {
            if (el.name) data[el.name] = el.value;
        });
        try {
            await API.setBotSettings(data);
            UI.toast('Configuración guardada', 'success');
        } catch (e) {
            UI.toast(e.message || 'Error al guardar', 'error');
        }
    },

    async saveConfigs() {
        const form = document.getElementById('form-config');
        const btn = form.querySelector('button.btn-primary');

        // Un solo request con todos los campos. Antes se mandaba un POST por
        // campo con Promise.all y el pool de conexiones no daba abasto: tardaba
        // 30s y avisaba error habiendo guardado casi todo.
        const values = {};
        form.querySelectorAll('input, select').forEach(el => {
            if (!el.name) return;
            // Una API Key vacía significa "no la toques", no "borrala". Sin esto,
            // guardar sin retipear la clave la dejaba en blanco y el bot se caía.
            if (el.type === 'password' && !el.value) return;
            values[el.name] = el.value;
        });

        if (btn) { btn.disabled = true; btn.textContent = 'Guardando...'; }
        try {
            await API.setConfigsBulk(values);
            UI.toast('Configuración guardada exitosamente', 'success');
        } catch (e) {
            UI.toast(e.message || 'Error al guardar configuración', 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = 'Guardar Todo'; }
        }
    },

    showLocationForm() {
        UI.modal(`
            <h3>Nueva Sede</h3>
            <form id="modal-form-location" style="display:flex;flex-direction:column;gap:1rem;">
                <div class="form-group">
                    <label>Nombre de la Sede</label>
                    <input type="text" name="name" required placeholder="Ej: Clínica Central">
                </div>
                <div class="form-group">
                    <label>Dirección</label>
                    <input type="text" name="address" placeholder="Ej: Av. Principal 123">
                </div>
                <div class="form-group">
                    <label>Teléfono</label>
                    <input type="text" name="phone" placeholder="Ej: 2604 123456">
                </div>
                <button type="submit" class="btn btn-primary">Crear Sede</button>
            </form>
        `);

        document.getElementById('modal-form-location').onsubmit = async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            try {
                await API.createLocation(data);
                UI.toast('Sede creada');
                UI.closeModal();
                Router.reload();
            } catch (err) { UI.toast(err.message, 'error'); }
        };
    },

    async deleteLocation(id) {
        if (await UI.confirm('¿Seguro quieres eliminar esta sede?')) {
            try {
                await API.deleteLocation(id);
                Router.reload();
            } catch (err) { UI.toast(err.message, 'error'); }
        }
    },

    showInsuranceForm(id = null, name = '', code = '', isActive = true) {
        const title = id ? 'Editar Obra Social' : 'Nueva Obra Social';
        const activeSelect = id ? `
            <div class="form-group">
                <label>Estado</label>
                <select name="is_active">
                    <option value="true" ${isActive ? 'selected' : ''}>Activa</option>
                    <option value="false" ${!isActive ? 'selected' : ''}>Inactiva</option>
                </select>
            </div>
        ` : '';

        UI.modal(`
            <h3>${title}</h3>
            <form id="modal-form-insurance" style="display:flex;flex-direction:column;gap:1rem;">
                <div class="form-group">
                    <label>Nombre de la Obra Social</label>
                    <input type="text" name="name" required placeholder="Ej: OSEP" value="${name}">
                </div>
                <div class="form-group">
                    <label>Código Interno</label>
                    <input type="text" name="code" placeholder="Ej: 101" value="${code}">
                </div>
                ${activeSelect}
                <button type="submit" class="btn btn-primary">${id ? 'Guardar Cambios' : 'Crear Obra Social'}</button>
            </form>
        `);

        document.getElementById('modal-form-insurance').onsubmit = async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            if (data.is_active !== undefined) {
                data.is_active = data.is_active === 'true';
            }
            try {
                if (id) {
                    await API.updateInsurance(id, data);
                    UI.toast('Obra social actualizada');
                } else {
                    await API.createInsurance(data);
                    UI.toast('Obra social creada');
                }
                UI.closeModal();
                Router.reload();
            } catch (err) { UI.toast(err.message, 'error'); }
        };
    },

    async deleteInsurance(id) {
        if (await UI.confirm('¿Eliminar esta obra social?')) {
            try {
                await API.deleteInsurance(id);
                Router.reload();
            } catch (err) { UI.toast(err.message, 'error'); }
        }
    }
};
