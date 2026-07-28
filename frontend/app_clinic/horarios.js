/**
 * Horarios / Disponibilidad
 * - Horario de atención de la clínica (compartido, editable).
 * - Ausencias puntuales por profesional.
 * Accesible para admin y recepción (rol clínica).
 */
const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];

Router.register('horarios', async (container) => {
    let blocks = [], professionals = [], timeoff = [];
    try {
        [blocks, professionals, timeoff] = await Promise.all([
            API.getSchedule(), API.getProfessionals(), API.getTimeOff()
        ]);
    } catch (e) {}

    HorariosPage.blocks = blocks.map(b => ({
        weekday: b.weekday,
        start_time: (b.start_time || '').slice(0, 5),
        end_time: (b.end_time || '').slice(0, 5),
    }));
    HorariosPage.professionals = professionals;

    container.innerHTML = `
        <div class="page-header"><h1>Horarios y Disponibilidad</h1></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;align-items:start;">
            <div class="card">
                <div class="card-header"><h2>🕒 Horario de atención</h2></div>
                <p style="font-size:.85rem;color:var(--slate-500);margin-bottom:1rem;">
                    Días y franjas en que la clínica atiende. El bot ofrece turnos solo dentro de estos horarios.
                </p>
                <div id="schedule-editor"></div>
                <button class="btn btn-primary" style="margin-top:1rem;" onclick="HorariosPage.save()">Guardar horarios</button>
            </div>

            <div class="card">
                <div class="card-header"><h2>🚫 Ausencias de profesionales</h2></div>
                <p style="font-size:.85rem;color:var(--slate-500);margin-bottom:1rem;">
                    Marcá un día en que un profesional no atiende. El bot no ofrecerá ese día y los turnos existentes aparecerán para reprogramar en el Dashboard.
                </p>
                <div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:end;margin-bottom:1rem;">
                    <div class="form-group" style="margin:0;">
                        <label>Profesional</label>
                        <select id="off-prof" class="form-control">
                            ${professionals.map(p => `<option value="${p.id}">${p.full_name}</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group" style="margin:0;">
                        <label>Fecha</label>
                        <input type="date" id="off-date" class="form-control">
                    </div>
                    <div class="form-group" style="margin:0;flex:1;min-width:120px;">
                        <label>Motivo (opcional)</label>
                        <input type="text" id="off-reason" class="form-control" placeholder="Ej: licencia">
                    </div>
                    <button class="btn btn-secondary" onclick="HorariosPage.addTimeOff()">Agregar</button>
                </div>
                <div id="timeoff-list"></div>
            </div>
        </div>
    `;

    HorariosPage.renderSchedule();
    HorariosPage.renderTimeOff(timeoff);
});

window.HorariosPage = {
    blocks: [],
    professionals: [],

    renderSchedule() {
        const el = document.getElementById('schedule-editor');
        el.innerHTML = DIAS.map((name, wd) => {
            const dayBlocks = this.blocks
                .map((b, idx) => ({ ...b, idx }))
                .filter(b => b.weekday === wd);
            return `
                <div style="padding:.5rem 0;border-bottom:1px solid var(--slate-100);">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <strong style="min-width:90px;display:inline-block;">${name}</strong>
                        <button class="btn btn-sm btn-ghost" style="color:var(--primary);" onclick="HorariosPage.addBlock(${wd})">+ franja</button>
                    </div>
                    ${dayBlocks.length === 0
                        ? `<div style="font-size:.8rem;color:var(--slate-400);">Cerrado</div>`
                        : dayBlocks.map(b => `
                            <div style="display:flex;gap:.4rem;align-items:center;margin-top:.35rem;">
                                <input type="time" value="${b.start_time}" class="form-control" style="width:auto;" onchange="HorariosPage.setTime(${b.idx},'start_time',this.value)">
                                <span>a</span>
                                <input type="time" value="${b.end_time}" class="form-control" style="width:auto;" onchange="HorariosPage.setTime(${b.idx},'end_time',this.value)">
                                <button class="btn btn-icon text-red" onclick="HorariosPage.removeBlock(${b.idx})">🗑️</button>
                            </div>
                        `).join('')}
                </div>
            `;
        }).join('');
    },

    addBlock(weekday) {
        this.blocks.push({ weekday, start_time: '09:00', end_time: '12:30' });
        this.renderSchedule();
    },
    removeBlock(idx) {
        this.blocks.splice(idx, 1);
        this.renderSchedule();
    },
    setTime(idx, field, value) {
        if (this.blocks[idx]) this.blocks[idx][field] = value;
    },

    async save() {
        const payload = this.blocks.filter(b => b.start_time && b.end_time);
        for (const b of payload) {
            if (b.end_time <= b.start_time) {
                UI.toast(`En ${DIAS[b.weekday]} el fin debe ser mayor al inicio`, 'error');
                return;
            }
        }
        try {
            await API.saveSchedule(payload);
            UI.toast('Horarios guardados', 'success');
        } catch (e) { UI.toast(e.message || 'Error al guardar', 'error'); }
    },

    renderTimeOff(list) {
        const el = document.getElementById('timeoff-list');
        if (!list || list.length === 0) {
            el.innerHTML = `<div style="font-size:.85rem;color:var(--slate-400);">Sin ausencias próximas.</div>`;
            return;
        }
        el.innerHTML = list.map(o => {
            const prof = o.professional ? o.professional.full_name : (this.professionals.find(p => p.id === o.professional_id)?.full_name || '?');
            return `
                <div style="padding:.5rem 0;border-bottom:1px solid var(--slate-100);display:flex;justify-content:space-between;align-items:center;">
                    <div>
                        <strong>${o.date}</strong> — ${prof}
                        <div style="font-size:.8rem;color:var(--slate-500);">${o.reason || ''}</div>
                    </div>
                    <button class="btn btn-icon text-red" onclick="HorariosPage.removeTimeOff('${o.id}')">🗑️</button>
                </div>
            `;
        }).join('');
    },

    async addTimeOff() {
        const professional_id = document.getElementById('off-prof').value;
        const date = document.getElementById('off-date').value;
        const reason = document.getElementById('off-reason').value.trim();
        if (!professional_id || !date) { UI.toast('Elegí profesional y fecha', 'error'); return; }
        try {
            await API.createTimeOff({ professional_id, date, reason: reason || null });
            UI.toast('Ausencia agregada', 'success');
            HorariosPage.renderTimeOff(await API.getTimeOff());
        } catch (e) { UI.toast(e.message || 'Error', 'error'); }
    },

    async removeTimeOff(id) {
        try {
            await API.deleteTimeOff(id);
            HorariosPage.renderTimeOff(await API.getTimeOff());
        } catch (e) { UI.toast(e.message || 'Error', 'error'); }
    },
};
