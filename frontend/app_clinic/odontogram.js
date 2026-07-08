/**
 * Odontogram Page - Interactive dental chart (FDI notation)
 * Replica de ficha odontológica OSPELSYM / estándar argentino
 * 
 * Layout:  Superior (Derecha: 18-11 | Izquierda: 21-28)
 *          Inferior (Derecha: 48-41 | Izquierda: 31-38)
 * 
 * Colores: ROJO = preexistente  |  AZUL = prestación nueva
 * Símbolos: X = extracción, O = caries, Corona, Prótesis fija/removible
 */

const TEETH = {
    upper_permanent: [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28],
    upper_deciduous: [55, 54, 53, 52, 51, 61, 62, 63, 64, 65],
    lower_deciduous: [85, 84, 83, 82, 81, 71, 72, 73, 74, 75],
    lower_permanent: [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38],
};

const SYMBOLS = [
    { id: 'cavity', label: 'Caries (O)', icon: '🔴' },
    { id: 'filling', label: 'Obturación', icon: '🔵' },
    { id: 'extraction', label: 'Extracción (X)', icon: '❌' },
    { id: 'missing', label: 'Ausente', icon: '🕳️' },
    { id: 'crown', label: 'Corona', icon: '⭕' },
    { id: 'sff', label: 'Sellador (SFF)', icon: '🏷️' },
    { id: 'fracture', label: 'Fractura', icon: '⚡' },
    { id: 'root_canal', label: 'Conducto', icon: '↓' },
    { id: 'bridge', label: 'Prótesis Fija', icon: '▭' },
    { id: 'implant', label: 'Implante', icon: '🔩' },
    { id: 'removable_prosthesis', label: 'Ortodoncia', icon: '═' },
];

let odontogramState = {
    patientId: null,
    selectedTool: 'filling',
    selectedCategory: 'preexisting',
    entries: [],
    patients: [],
    selectedFaces: [],
};

Router.register('odontogram', async (container) => {
    const storedPatientId = sessionStorage.getItem('odontogram_patient_id');
    let patients = [];
    try { patients = await API.getPatients(); } catch (e) {}
    odontogramState.patients = patients;

    container.innerHTML = `
        <div class="page-header">
            <div>
                <h1>Odontograma Digital</h1>
                <p style="color:var(--slate-500);font-size:.85rem;">Ficha Odontológica Estándar (OSPELSYM / Nacional)</p>
            </div>
        </div>

        <div class="odontogram-container">
            <!-- Instructions Card -->
            <div class="card" style="background:var(--primary-light);border-color:var(--primary);margin-bottom:1rem;">
                <div style="display:flex;gap:1rem;align-items:center;">
                    <div style="font-size:1.5rem;">💡</div>
                    <div style="font-size:.85rem;color:var(--primary-dark);">
                        <strong>Cómo usar:</strong> 1. Seleccioná el paciente. 2. Elegí <strong>Categoría</strong> (Rojo para existente, Azul para nuevo). 
                        3. Elegí un <strong>Símbolo</strong>. 4. Hacé clic en la <strong>cara del diente</strong> (o en el número para aplicar al diente completo).
                    </div>
                </div>
            </div>

            <!-- Patient Selector -->
            <div class="card">
                <div class="odontogram-patient-select">
                    <label style="font-weight:600;color:var(--slate-700);">Paciente:</label>
                    <select id="odo-patient" style="padding:.5rem .85rem;border:1px solid var(--slate-300);border-radius:var(--radius);min-width:300px;font-size:.9rem;">
                        <option value="">Seleccionar paciente...</option>
                        ${patients.map(p => `<option value="${p.id}" ${p.id === storedPatientId ? 'selected' : ''}>${p.last_name}, ${p.first_name} — DNI: ${p.dni}</option>`).join('')}
                    </select>
                    <div id="odo-insurance" style="font-weight:600;color:var(--primary);"></div>
                </div>
            </div>

            <!-- Toolbar -->
            <div class="odontogram-toolbar" style="flex-wrap: wrap; gap: 1rem; row-gap: 1.5rem; align-items: center;">
                <div class="tool-group">
                    <span class="tool-group-label">Categoría:</span>
                    <button class="tool-btn tool-red active" data-category="preexisting" onclick="OdontogramPage.setCategory('preexisting', this)">🔴 Preexistente</button>
                    <button class="tool-btn tool-blue" data-category="treatment" onclick="OdontogramPage.setCategory('treatment', this)">🔵 Prestación</button>
                </div>
                <div class="tool-group" style="border-left:1px solid var(--slate-300);padding-left:1rem;">
                    <span class="tool-group-label">Símbolo:</span>
                    <div style="display:flex;gap:.25rem;flex-wrap:wrap;">
                        ${SYMBOLS.map((s, i) => `
                            <button class="tool-btn ${i === 0 ? 'active' : ''}" data-symbol="${s.id}" 
                                onclick="OdontogramPage.setTool('${s.id}', this)" title="${s.label}">
                                ${s.icon} ${s.label}
                            </button>
                        `).join('')}
                    </div>
                </div>
                <div class="tool-group odo-priority-group" style="border-left:1px solid var(--slate-300);padding-left:1rem;display:none;">
                    <span class="tool-group-label">Prioridad:</span>
                    <select id="odo-priority" style="padding:.35rem .5rem;border:1px solid var(--slate-300);border-radius:var(--radius);font-size:.85rem;background:white;color:var(--slate-700);font-weight:600;">
                        <option value="Baja">Baja</option>
                        <option value="Media" selected>Media</option>
                        <option value="Alta">Alta</option>
                    </select>
                </div>
                <div class="tool-group" style="border-left:1px solid var(--slate-300);padding-left:1rem;display:flex;gap:.5rem;align-items:center;">
                    <div style="display:flex;flex-direction:column;gap:.25rem;">
                        <label style="font-size:.7rem;font-weight:600;color:var(--slate-500);text-transform:uppercase;">Código OS:</label>
                        <input type="text" id="odo-code" placeholder="Código" style="width:70px;padding:.35rem;border:1px solid var(--slate-300);border-radius:var(--radius);font-size:.85rem;">
                    </div>
                    <div style="display:flex;flex-direction:column;gap:.25rem;">
                        <label style="font-size:.7rem;font-weight:600;color:var(--slate-500);text-transform:uppercase;">Descripción:</label>
                        <input type="text" id="odo-desc" placeholder="Descripción" style="width:120px;padding:.35rem;border:1px solid var(--slate-300);border-radius:var(--radius);font-size:.85rem;">
                    </div>
                </div>
                <div class="tool-group" style="border-left:1px solid var(--slate-300);padding-left:1rem;display:flex;align-items:center;gap:.5rem;margin-left:auto;">
                    <button id="odo-bulk-save" class="btn btn-primary" style="padding:.5rem 1rem;font-size:.85rem;" onclick="OdontogramPage.saveBulk()" disabled>
                        Guardar Selección (0)
                    </button>
                    <button id="odo-bulk-clear" class="btn btn-secondary" style="padding:.5rem 1rem;font-size:.85rem;" onclick="OdontogramPage.clearSelection()" disabled>
                        Limpiar
                    </button>
                </div>
            </div>

            <!-- Dental Chart -->
            <div class="odontogram-chart" id="odo-chart">
                <div class="odontogram-labels-horizontal">
                    <span>DERECHA</span>
                    <span>IZQUIERDA</span>
                </div>

                <!-- Permanent Teeth Rows -->
                <div class="odontogram-row permanent">
                    ${TEETH.upper_permanent.map((t, i) => (i === 8 ? '<div class="quadrant-separator"></div>' : '') + OdontogramPage.renderTooth(t)).join('')}
                </div>
                <div class="odontogram-row permanent" style="margin-top:1rem;">
                    ${TEETH.lower_permanent.map((t, i) => (i === 8 ? '<div class="quadrant-separator"></div>' : '') + OdontogramPage.renderTooth(t)).join('')}
                </div>

                <!-- Deciduous Teeth Rows -->
                <div style="margin-top:3rem; padding-top:2rem; border-top:1px dashed var(--slate-300); width:100%; display:flex; flex-direction:column; align-items:center;">
                    <div style="font-size:.7rem; color:var(--slate-500); margin-bottom:1.5rem; text-align:center; font-weight:700; text-transform:uppercase; letter-spacing:.1em;">DIENTES TEMPORARIOS</div>
                    <div class="odontogram-row deciduous">
                        ${TEETH.upper_deciduous.map((t, i) => (i === 5 ? '<div class="quadrant-separator"></div>' : '') + OdontogramPage.renderTooth(t)).join('')}
                    </div>
                </div>
                <div class="odontogram-row deciduous" style="margin-top:1rem;">
                    ${TEETH.lower_deciduous.map((t, i) => (i === 5 ? '<div class="quadrant-separator"></div>' : '') + OdontogramPage.renderTooth(t)).join('')}
                </div>

                <!-- Legend -->
                <div class="odontogram-legend" style="margin-top:2rem; display:grid; grid-template-columns: repeat(3, 1fr); gap: 1rem;">
                    <div>
                        <div class="legend-item"><div class="legend-swatch" style="border:2px solid var(--odo-preexisting); border-radius:50%"></div> Corona Preexistente</div>
                        <div class="legend-item"><div class="legend-swatch" style="border:2px solid var(--odo-treatment); border-radius:50%"></div> Corona a realizar</div>
                        <div class="legend-item"><div class="legend-swatch" style="background:var(--odo-preexisting);"></div> Caries / Obt. Roja</div>
                    </div>
                    <div>
                        <div class="legend-item"><span style="color:var(--odo-preexisting);font-weight:800;">✕</span> Diente a extraer (Rojo)</div>
                        <div class="legend-item"><span style="color:var(--odo-treatment);font-weight:800;">✕</span> Diente ausente (Azul)</div>
                        <div class="legend-item"><div class="legend-swatch" style="background:var(--odo-treatment);"></div> Obturación Azul</div>
                    </div>
                    <div>
                        <div class="legend-item"><strong>SFF</strong> Sellador de fosas</div>
                        <div class="legend-item"><strong>⚡</strong> Fractura coronaria</div>
                        <div class="legend-item"><strong>↓</strong> Tratamiento conducto</div>
                        <div class="legend-item"><strong>═</strong> Presencia de aparato de ortodoncia</div>
                    </div>
                </div>
            </div>

            <!-- Entries Table -->
            <div class="card odontogram-entries">
                <div class="card-header">
                    <h2>Registro de Prestaciones</h2>
                    <button class="btn btn-sm btn-primary" onclick="OdontogramPage.showEntryForm()">+ Registro Manual</button>
                </div>
                <div id="odo-entries-table" class="table-container">
                    <div class="empty-state">
                        <div class="empty-state-icon">🦷</div>
                        <div class="empty-state-text">Seleccioná un paciente para ver su ficha</div>
                    </div>
                </div>
            </div>

            <!-- Pending Treatments Card (RF-003) -->
            <div class="card" id="odo-pending-card" style="margin-top: 1.5rem;">
                <div class="card-header">
                    <h2>Trabajos Pendientes por Prioridad</h2>
                </div>
                <div id="odo-pending-treatments" class="table-container">
                    <div class="empty-state">
                        <div class="empty-state-icon">📋</div>
                        <div class="empty-state-text">Seleccioná un paciente para ver sus trabajos pendientes</div>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Listen for patient change
    document.getElementById('odo-patient').addEventListener('change', (e) => {
        odontogramState.patientId = e.target.value || null;
        odontogramState.selectedFaces = [];
        if (odontogramState.patientId) {
            const p = patients.find(p => p.id === odontogramState.patientId);
            document.getElementById('odo-insurance').textContent = p ? `Obra Social: ${p.insurance_name || 'Particular'}` : '';
            OdontogramPage.loadEntries();
        } else {
            document.getElementById('odo-insurance').textContent = '';
            OdontogramPage.clearChart();
            OdontogramPage.updateSelectionUI();
        }
    });

    if (storedPatientId) {
        odontogramState.patientId = storedPatientId;
        sessionStorage.removeItem('odontogram_patient_id');
        const p = patients.find(p => p.id === storedPatientId);
        if (p) document.getElementById('odo-insurance').textContent = `Obra Social: ${p.insurance_name || 'Particular'}`;
        OdontogramPage.loadEntries();
    }
});


const OdontogramPage = {
    renderTooth(number) {
        return `
            <div class="tooth" id="tooth-${number}" data-tooth="${number}">
                <div class="tooth-number" onclick="OdontogramPage.clickFace(${number}, 'full')">${number}</div>
                <div class="tooth-diagram" id="diagram-${number}">
                    <div class="tooth-face tooth-face-vestibular" data-tooth="${number}" data-face="vestibular" onclick="OdontogramPage.clickFace(${number}, 'vestibular', this)"></div>
                    <div class="tooth-face tooth-face-mesial" data-tooth="${number}" data-face="mesial" onclick="OdontogramPage.clickFace(${number}, 'mesial', this)"></div>
                    <div class="tooth-face tooth-face-oclusal" data-tooth="${number}" data-face="oclusal" onclick="OdontogramPage.clickFace(${number}, 'oclusal', this)"></div>
                    <div class="tooth-face tooth-face-distal" data-tooth="${number}" data-face="distal" onclick="OdontogramPage.clickFace(${number}, 'distal', this)"></div>
                    <div class="tooth-face tooth-face-palatina" data-tooth="${number}" data-face="palatina" onclick="OdontogramPage.clickFace(${number}, 'palatina', this)"></div>
                    <div class="tooth-overlay" id="overlay-${number}"></div>
                </div>
                <div class="tooth-label-container" id="label-container-${number}"></div>
            </div>
        `;
    },

    setTool(symbol, btn) {
        odontogramState.selectedTool = symbol;
        btn.closest('.tool-group').querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
    },

    setCategory(category, btn) {
        odontogramState.selectedCategory = category;
        btn.closest('.tool-group').querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        
        const priorityGroup = document.querySelector('.odo-priority-group');
        if (priorityGroup) {
            priorityGroup.style.display = category === 'treatment' ? 'block' : 'none';
        }
    },

    updateSelectionUI() {
        document.querySelectorAll('.tooth-face').forEach(f => f.classList.remove('selected-face'));
        document.querySelectorAll('.tooth').forEach(t => t.classList.remove('selected-tooth'));

        odontogramState.selectedFaces.forEach(sf => {
            if (sf.face === 'full') {
                const toothEl = document.getElementById(`tooth-${sf.tooth_number}`);
                if (toothEl) toothEl.classList.add('selected-tooth');
            } else {
                const faceEl = document.querySelector(`[data-tooth="${sf.tooth_number}"][data-face="${sf.face}"]`);
                if (faceEl) faceEl.classList.add('selected-face');
            }
        });

        const count = odontogramState.selectedFaces.length;
        const saveBtn = document.getElementById('odo-bulk-save');
        const clearBtn = document.getElementById('odo-bulk-clear');
        
        if (saveBtn) {
            saveBtn.disabled = count === 0;
            saveBtn.textContent = `Guardar Selección (${count})`;
        }
        if (clearBtn) {
            clearBtn.disabled = count === 0;
        }
    },

    clearSelection() {
        odontogramState.selectedFaces = [];
        this.updateSelectionUI();
    },

    async saveBulk() {
        if (!odontogramState.patientId) return UI.toast('Seleccioná un paciente primero', 'error');
        if (odontogramState.selectedFaces.length === 0) return;

        const codeVal = document.getElementById('odo-code')?.value || '';
        const descVal = document.getElementById('odo-desc')?.value || '';
        const priorityVal = document.getElementById('odo-priority')?.value || null;

        const payload = odontogramState.selectedFaces.map(sf => ({
            patient_id: sf.patient_id,
            tooth_number: sf.tooth_number,
            face: sf.face,
            symbol: sf.symbol,
            category: sf.category,
            procedure_code: codeVal || null,
            description: descVal || null,
            priority: sf.category === 'treatment' ? priorityVal : null,
        }));

        try {
            await API.createOdontogramEntriesBulk(payload);
            odontogramState.selectedFaces = [];
            
            const codeInput = document.getElementById('odo-code');
            const descInput = document.getElementById('odo-desc');
            if (codeInput) codeInput.value = '';
            if (descInput) descInput.value = '';
            
            this.updateSelectionUI();
            this.loadEntries();
            UI.toast('Registros guardados con éxito', 'success');
        } catch (err) {
            UI.toast(err.message, 'error');
        }
    },

    _clickTimer: null,
    async clickFace(toothNumber, face, el) {
        if (!odontogramState.patientId) return UI.toast('Seleccioná un paciente primero', 'error');

        if (this._clickTimer) {
            clearTimeout(this._clickTimer);
            this._clickTimer = null;
            this.deleteLastForToothFace(toothNumber, face);
            return;
        }

        const tool = odontogramState.selectedTool;
        const category = odontogramState.selectedCategory;
        const fullToothSymbols = ['extraction', 'missing', 'crown', 'root_canal', 'bridge', 'fixed_prosthesis', 'implant', 'removable_prosthesis', 'removible', 'fracture', 'sff'];
        const effectiveFace = (fullToothSymbols.includes(tool) || face === 'full') ? 'full' : face;

        this._clickTimer = setTimeout(() => {
            this._clickTimer = null;
            
            // Toggle selection
            const index = odontogramState.selectedFaces.findIndex(sf => sf.tooth_number === toothNumber && sf.face === effectiveFace);
            if (index > -1) {
                odontogramState.selectedFaces.splice(index, 1);
            } else {
                odontogramState.selectedFaces.push({
                    patient_id: odontogramState.patientId,
                    tooth_number: toothNumber,
                    face: effectiveFace,
                    symbol: tool,
                    category: category
                });
            }
            
            this.updateSelectionUI();
        }, 250);
    },

    async deleteLastForToothFace(toothNumber, face) {
        // Find most recent entry for this specific tooth and face sector (or 'full' if clicked on number)
        const reversedEntries = [...odontogramState.entries].reverse();
        const entry = reversedEntries.find(e => {
            if (e.tooth_number !== toothNumber) return false;
            if (face === 'full') return e.face === 'full';
            // If face clicked is mesial, we can delete 'full' ones or 'mesial' ones
            return e.face === face || e.face === 'full';
        });

        if (entry) {
            try {
                await API.deleteOdontogramEntry(entry.id);
                this.loadEntries();
                UI.toast('Registro eliminado', 'info');
            } catch (err) { UI.toast(err.message, 'error'); }
        }
    },

    async loadEntries() {
        if (!odontogramState.patientId) return;

        try {
            const entries = await API.getOdontogram(odontogramState.patientId);
            odontogramState.entries = entries;
            this.renderChart(entries);
            this.renderEntriesTable(entries);
            this.renderPendingTreatments(entries);
        } catch (err) {
            UI.toast(err.message, 'error');
        }
    },

    renderChart(entries) {
        // Reset all teeth
        document.querySelectorAll('.tooth-face').forEach(f => {
            f.classList.remove('preexisting', 'treatment', 'fill-red', 'fill-blue');
        });
        document.querySelectorAll('.tooth-overlay').forEach(o => {
            o.textContent = '';
            o.className = 'tooth-overlay';
            o.style.color = '';
        });
        document.querySelectorAll('.tooth-label-container').forEach(l => {
            l.textContent = '';
            l.className = 'tooth-label-container';
        });

        entries.forEach(e => {
            const isPre = e.category === 'preexisting';
            const colorClass = isPre ? 'preexisting' : 'treatment';
            const overlay = document.getElementById(`overlay-${e.tooth_number}`);
            const labelContainer = document.getElementById(`label-container-${e.tooth_number}`);

            const isFullSymbol = [
                'extraction', 'missing', 'crown', 'fracture', 'root_canal', 
                'bridge', 'fixed_prosthesis', 'implant', 'removable_prosthesis', 'removible', 'sff'
            ].includes(e.symbol);

            if (e.face === 'full' || e.face === 'Diente' || isFullSymbol) {
                if (overlay) {
                    overlay.classList.add(colorClass);
                    
                    if (e.symbol === 'extraction' || e.symbol === 'missing') {
                        overlay.textContent = '✕';
                        overlay.classList.add(e.symbol === 'extraction' ? 'extraction-red' : 'extraction-blue');
                    } else if (e.symbol === 'crown') {
                        overlay.classList.add('crown-circle');
                    } else if (e.symbol === 'fracture') {
                        overlay.classList.add('fracture-zigzag');
                        overlay.textContent = '⚡';
                    } else if (e.symbol === 'root_canal') {
                        overlay.textContent = '↓';
                        overlay.classList.add('root-canal-mark');
                    } else if (e.symbol === 'bridge' || e.symbol === 'fixed_prosthesis') {
                        overlay.classList.add('bridge-line');
                    } else if (e.symbol === 'implant') {
                        overlay.textContent = '🔩';
                        overlay.classList.add('implant-mark');
                    } else if (e.symbol === 'removable_prosthesis' || e.symbol === 'removible') {
                        overlay.classList.add('removable-mark');
                    }
                }
                
                if (e.symbol === 'sff' && labelContainer) {
                    labelContainer.textContent = 'SFF';
                    labelContainer.classList.add('sff-label', colorClass);
                }

                if (e.symbol === 'cavity' || e.symbol === 'filling') {
                    const faces = document.querySelectorAll(`[data-tooth="${e.tooth_number}"].tooth-face`);
                    faces.forEach(f => f.classList.add(isPre ? 'fill-red' : 'fill-blue'));
                }
            } else {
                // Individual faces
                const faceEl = document.querySelector(`[data-tooth="${e.tooth_number}"][data-face="${e.face}"]`);
                if (faceEl) {
                    if (e.symbol === 'cavity' || e.symbol === 'filling') {
                        faceEl.classList.add(isPre ? 'fill-red' : 'fill-blue');
                    }
                }
            }
        });
        this.updateSelectionUI();
    },

    renderEntriesTable(entries) {
        const container = document.getElementById('odo-entries-table');
        if (entries.length === 0) {
            container.innerHTML = `<div class="empty-state"><div class="empty-state-text">Sin registros históricos</div></div>`;
            return;
        }

        const faceLabels = { mesial: 'M', distal: 'D', vestibular: 'V', palatina: 'P/L', oclusal: 'O', full: 'Diente' };
        
        container.innerHTML = `
            <table>
                <thead>
                    <tr>
                        <th>Fecha</th>
                        <th>Diente</th>
                        <th>Cara</th>
                        <th>Prestación</th>
                        <th>Prioridad</th>
                        <th>Código</th>
                        <th>Mat. Prof.</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    ${entries.map(e => `
                        <tr class="${e.category === 'preexisting' ? 'row-preexisting' : 'row-treatment'}" 
                            ondblclick="OdontogramPage.deleteEntry('${e.id}')" 
                            title="Doble clic para eliminar"
                            style="cursor:pointer">
                            <td>${UI.formatDate(e.created_at)}</td>
                            <td><strong>${e.tooth_number}</strong></td>
                            <td>${faceLabels[e.face] || e.face}</td>
                            <td>${SYMBOLS.find(s => s.id === e.symbol)?.label || e.symbol}</td>
                            <td>
                                ${e.category === 'treatment' ? `
                                    <span class="badge ${e.priority === 'Alta' ? 'badge-cancelled' : (e.priority === 'Media' ? 'badge-pending' : 'badge-confirmed')}">
                                        ${e.priority || 'Baja'}
                                    </span>
                                ` : '-'}
                            </td>
                            <td>${e.procedure_code || '-'}</td>
                            <td>${e.description || '-'}</td>
                            <td style="text-align:right">
                                <button class="btn btn-sm btn-ghost" onclick="OdontogramPage.deleteEntry('${e.id}')">✕</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    },

    clearChart() {
        document.querySelectorAll('.tooth-face').forEach(f => f.classList.remove('preexisting', 'treatment'));
        document.querySelectorAll('.tooth-overlay').forEach(o => o.textContent = '');
        document.getElementById('odo-entries-table').innerHTML = `<div class="empty-state"><div class="empty-state-text">Seleccioná un paciente</div></div>`;
    },

    async deleteEntry(id) {
        const ok = await UI.confirm('¿Eliminar registro?', 'Esta acción no se puede deshacer.');
        if (ok) {
            try {
                await API.deleteOdontogramEntry(id);
                this.loadEntries();
            } catch (err) { UI.toast(err.message, 'error'); }
        }
    },

    showEntryForm() {
        if (!odontogramState.patientId) return UI.toast('Seleccioná un paciente', 'error');
        
        const allTeeth = [...TEETH.upper_permanent, ...TEETH.upper_deciduous, ...TEETH.lower_deciduous, ...TEETH.lower_permanent];
        const body = `
            <form id="form-odo-entry" class="form-grid">
                <div class="form-group form-group-full">
                    <label>Dientes (seleccionar uno o más)</label>
                    <div class="teeth-selector">
                        ${allTeeth.map(t => `
                            <label class="tooth-check">
                                <input type="checkbox" name="teeth" value="${t}">
                                <span>${t}</span>
                            </label>
                        `).join('')}
                    </div>
                </div>
                <div class="form-group form-group-full">
                    <label>Caras (seleccionar una o más)</label>
                    <div class="face-checkboxes">
                        <label class="face-check">
                            <input type="checkbox" name="faces" value="full" checked>
                            <span>Diente completo</span>
                        </label>
                        <label class="face-check">
                            <input type="checkbox" name="faces" value="oclusal">
                            <span>Oclusal (O)</span>
                        </label>
                        <label class="face-check">
                            <input type="checkbox" name="faces" value="vestibular">
                            <span>Vestibular (V)</span>
                        </label>
                        <label class="face-check">
                            <input type="checkbox" name="faces" value="palatina">
                            <span>Palatina/Lingual (P/L)</span>
                        </label>
                        <label class="face-check">
                            <input type="checkbox" name="faces" value="mesial">
                            <span>Mesial (M)</span>
                        </label>
                        <label class="face-check">
                            <input type="checkbox" name="faces" value="distal">
                            <span>Distal (D)</span>
                        </label>
                    </div>
                </div>
                <div class="form-group">
                    <label>Símbolo</label>
                    <select name="symbol">${SYMBOLS.map(s => `<option value="${s.id}">${s.icon} ${s.label}</option>`).join('')}</select>
                </div>
                <div class="form-group">
                    <label>Categoría</label>
                    <select name="category" onchange="document.querySelector('.odo-manual-priority').style.display = this.value === 'treatment' ? 'block' : 'none';">
                        <option value="preexisting">🔴 Preexistente</option>
                        <option value="treatment">🔵 Prestación nueva</option>
                    </select>
                </div>
                <div class="form-group odo-manual-priority" style="display:none;">
                    <label>Prioridad</label>
                    <select name="priority">
                        <option value="Baja">Baja</option>
                        <option value="Media" selected>Media</option>
                        <option value="Alta">Alta</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Código OS</label>
                    <input type="text" name="procedure_code" placeholder="Ej: 0216">
                </div>
                <div class="form-group">
                    <label>Descripción / Matrícula</label>
                    <input type="text" name="description">
                </div>
            </form>
            <div id="entry-preview" style="margin-top:.75rem;font-size:.8rem;color:var(--slate-500);"></div>
        `;
        UI.showModal('Registro Manual', body, `
            <button class="btn btn-secondary" onclick="UI.closeModal()">Cancelar</button>
            <button class="btn btn-primary" onclick="OdontogramPage.saveEntry()">Guardar</button>
        `);

        // Live preview of how many entries will be created
        const updatePreview = () => {
            const teeth = document.querySelectorAll('#form-odo-entry input[name="teeth"]:checked').length;
            const faces = document.querySelectorAll('#form-odo-entry input[name="faces"]:checked').length;
            const total = teeth * faces;
            const preview = document.getElementById('entry-preview');
            if (preview) preview.textContent = total > 0 ? `Se crearán ${total} registro(s) (${teeth} diente(s) × ${faces} cara(s))` : 'Seleccioná al menos un diente y una cara';
        };
        document.querySelectorAll('#form-odo-entry input[type="checkbox"]').forEach(cb => cb.addEventListener('change', updatePreview));
        updatePreview();
    },

    async saveEntry() {
        const form = document.getElementById('form-odo-entry');
        const selectedTeeth = [...form.querySelectorAll('input[name="teeth"]:checked')].map(cb => parseInt(cb.value));
        const selectedFaces = [...form.querySelectorAll('input[name="faces"]:checked')].map(cb => cb.value);
        
        if (selectedTeeth.length === 0) return UI.toast('Seleccioná al menos un diente', 'error');
        if (selectedFaces.length === 0) return UI.toast('Seleccioná al menos una cara', 'error');

        const category = form.querySelector('[name="category"]').value;
        const baseData = {
            patient_id: odontogramState.patientId,
            symbol: form.querySelector('[name="symbol"]').value,
            category: category,
            procedure_code: form.querySelector('[name="procedure_code"]').value || null,
            description: form.querySelector('[name="description"]').value || null,
            priority: category === 'treatment' ? form.querySelector('[name="priority"]').value : null,
        };

        // Build bulk payload: one entry per tooth × face combination
        const payload = [];
        for (const tooth of selectedTeeth) {
            for (const face of selectedFaces) {
                payload.push({ ...baseData, tooth_number: tooth, face: face });
            }
        }

        try {
            await API.createOdontogramEntriesBulk(payload);
            UI.closeModal();
            this.loadEntries();
            UI.toast(`${payload.length} registro(s) guardado(s)`, 'success');
        } catch (err) { UI.toast(err.message, 'error'); }
    }
};
