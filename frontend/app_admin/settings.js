/**
 * Settings Admin Page
 */
Router.register('settings', async (container) => {
    let locations = [];
    let insurances = [];
    let configs = [];
    try {
        [locations, insurances, configs] = await Promise.all([
            API.getLocations(), 
            API.getInsurances(),
            API.getConfigs()
        ]);
    } catch (e) {}

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
                <form id="form-config" style="display:flex;flex-direction:column;gap:1rem;padding-top:.5rem;">
                    <div class="form-group">
                        <label>Telegram Bot Token</label>
                        <input type="password" name="TELEGRAM_BOT_TOKEN" value="${getConfig('TELEGRAM_BOT_TOKEN')}" placeholder="123456:ABC-DEF...">
                        <small style="color:var(--slate-400)">Token proporcionado por @BotFather</small>
                    </div>
                    <div class="form-group">
                        <label>OpenAI API Key</label>
                        <input type="password" name="OPENAI_API_KEY" value="${getConfig('OPENAI_API_KEY')}" placeholder="sk-...">
                        <small style="color:var(--slate-400)">Necesario para el cerebro del bot (GPT-4o)</small>
                    </div>
                    <div class="form-group">
                        <label>WhatsApp (Meta/Twilio API Key)</label>
                        <input type="text" name="WHATSAPP_API_KEY" value="${getConfig('WHATSAPP_API_KEY')}" placeholder="Configuración de WhatsApp...">
                    </div>
                    <div class="form-group">
                        <label>Webhook URL</label>
                        <input type="text" name="TELEGRAM_WEBHOOK_URL" value="${getConfig('TELEGRAM_WEBHOOK_URL')}" placeholder="https://tu-dominio.com/api/bot/webhook">
                    </div>
                    <button type="button" class="btn btn-primary" onclick="SettingsPage.saveConfigs()">Guardar Configuración</button>
                    <p style="font-size:.75rem;color:var(--slate-500);margin-top:.5rem;">⚠️ La mayoría de los cambios requieren reiniciar los contenedores para aplicarse.</p>
                </form>
            </div>
        </div>
    `;
});

window.SettingsPage = {
    async saveConfigs() {
        const form = document.getElementById('form-config');
        const inputs = form.querySelectorAll('input');
        const tasks = [];
        
        inputs.forEach(input => {
            tasks.push(API.setConfig(input.name, input.value));
        });

        try {
            await Promise.all(tasks);
            UI.toast('Configuración guardada exitosamente', 'success');
        } catch (e) {
            UI.toast('Error al guardar configuración', 'error');
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
                Router.load('settings');
            } catch (err) { UI.toast(err.message, 'error'); }
        };
    },

    async deleteLocation(id) {
        if (await UI.confirm('¿Seguro quieres eliminar esta sede?')) {
            try {
                await API.deleteLocation(id);
                Router.load('settings');
            } catch (err) { UI.toast(err.message, 'error'); }
        }
    },

    showInsuranceForm() {
        UI.modal(`
            <h3>Nueva Obra Social</h3>
            <form id="modal-form-insurance" style="display:flex;flex-direction:column;gap:1rem;">
                <div class="form-group">
                    <label>Nombre de la Obra Social</label>
                    <input type="text" name="name" required placeholder="Ej: OSEP">
                </div>
                <div class="form-group">
                    <label>Código Interno</label>
                    <input type="text" name="code" placeholder="Ej: 101">
                </div>
                <button type="submit" class="btn btn-primary">Crear Obra Social</button>
            </form>
        `);

        document.getElementById('modal-form-insurance').onsubmit = async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            try {
                await API.createInsurance(data);
                UI.toast('Obra social creada');
                Router.load('settings');
            } catch (err) { UI.toast(err.message, 'error'); }
        };
    },

    async deleteInsurance(id) {
        if (await UI.confirm('¿Eliminar esta obra social?')) {
            try {
                await API.deleteInsurance(id);
                Router.load('settings');
            } catch (err) { UI.toast(err.message, 'error'); }
        }
    }
};
