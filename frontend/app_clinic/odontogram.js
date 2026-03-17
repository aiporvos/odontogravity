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
    upper_right: [18, 17, 16, 15, 14, 13, 12, 11],
    upper_left:  [21, 22, 23, 24, 25, 26, 27, 28],
    lower_right: [48, 47, 46, 45, 44, 43, 42, 41],
    lower_left:  [31, 32, 33, 34, 35, 36, 37, 38],
};

// Deciduous teeth (optional)
const DECIDUOUS_TEETH = {
    upper_right: [55, 54, 53, 52, 51],
    upper_left:  [61, 62, 63, 64, 65],
    lower_right: [85, 84, 83, 82, 81],
    lower_left:  [71, 72, 73, 74, 75],
};

const FACES = ['vestibular', 'distal', 'oclusal', 'mesial', 'palatina'];
const SYMBOLS = [
    { id: 'filling', label: 'Relleno', icon: '▬' },
    { id: 'cavity', label: 'Caries (O)', icon: 'O' },
    { id: 'extraction', label: 'Extracción (X)', icon: 'X' },
    { id: 'missing', label: 'Ausente', icon: '—' },
    { id: 'crown', label: 'Corona', icon: '⌓' },
    { id: 'root_canal', label: 'Conducto', icon: '↓' },
    { id: 'fixed_prosthesis', label: 'Prót. Fija', icon: '▭' },
    { id: 'removable_prosthesis', label: 'Prót. Remov.', icon: '▯' },
    { id: 'implant', label: 'Implante', icon: '⊥' },
];

let odontogramState = {
    patientId: null,
    selectedTool: 'filling',
    selectedCategory: 'preexisting',
    entries: [],
    patients: [],
};

Router.register('odontogram', async (container) => {
    // Check if coming from patient page
    const storedPatientId = sessionStorage.getItem('odontogram_patient_id');

    let patients = [];
    try { patients = await API.getPatients(); } catch (e) {}
    odontogramState.patients = patients;

    container.innerHTML = `
        <div class="page-header">
            <h1>Odontograma Digital</h1>
        </div>

        <div class="odontogram-container">
            <!-- Patient Selector -->
            <div class="card">
                <div class="odontogram-patient-select">
                    <label style="font-weight:600;color:var(--slate-700);">Paciente:</label>
                    <select id="odo-patient" style="padding:.5rem .85rem;border:1px solid var(--slate-300);border-radius:var(--radius);min-width:300px;font-size:.9rem;">
                        <option value="">Seleccionar paciente...</option>
                        ${patients.map(p => `<option value="${p.id}" ${p.id === storedPatientId ? 'selected' : ''}>${p.last_name}, ${p.first_name} — DNI: ${p.dni}</option>`).join('')}
                    </select>
                    <span id="odo-insurance" style="color:var(--slate-500);font-size:.85rem;"></span>
                </div>
            </div>

            <!-- Toolbar -->
            <div class="odontogram-toolbar">
                <div class="tool-group">
                    <span class="tool-group-label">Categoría:</span>
                    <button class="tool-btn tool-red active" data-category="preexisting" onclick="OdontogramPage.setCategory('preexisting', this)">🔴 Preexistente</button>
                    <button class="tool-btn tool-blue" data-category="treatment" onclick="OdontogramPage.setCategory('treatment', this)">🔵 Prestación</button>
                </div>
                <div class="tool-group">
                    <span class="tool-group-label">Símbolo:</span>
                    ${SYMBOLS.map((s, i) => `
                        <button class="tool-btn ${i === 0 ? 'active' : ''}" data-symbol="${s.id}" 
                            onclick="OdontogramPage.setTool('${s.id}', this)" title="${s.label}">
                            ${s.icon} ${s.label}
                        </button>
                    `).join('')}
                </div>
            </div>

            <!-- Dental Chart -->
            <div class="odontogram-chart" id="odo-chart">
                <!-- Upper Arch -->
                <div class="odontogram-arch">
                    <div class="odontogram-arch-label">Superior</div>
                    <div class="odontogram-row">
                        <div class="odontogram-quadrant" id="quad-upper-right">
                            <span class="odontogram-arch-label" style="align-self:center;margin-right:.5rem;font-size:.7rem;">Derecha</span>
                            ${TEETH.upper_right.map(t => OdontogramPage.renderTooth(t, 'upper')).join('')}
                        </div>
                        <div class="quadrant-separator"></div>
                        <div class="odontogram-quadrant" id="quad-upper-left">
                            ${TEETH.upper_left.map(t => OdontogramPage.renderTooth(t, 'upper')).join('')}
                            <span class="odontogram-arch-label" style="align-self:center;margin-left:.5rem;font-size:.7rem;">Izquierda</span>
                        </div>
                    </div>
                </div>

                <!-- Separator -->
                <div style="width:100%;height:1px;background:var(--slate-300);"></div>

                <!-- Lower Arch -->
                <div class="odontogram-arch">
                    <div class="odontogram-row">
                        <div class="odontogram-quadrant" id="quad-lower-right">
                            <span class="odontogram-arch-label" style="align-self:center;margin-right:.5rem;font-size:.7rem;">Derecha</span>
                            ${TEETH.lower_right.map(t => OdontogramPage.renderTooth(t, 'lower')).join('')}
                        </div>
                        <div class="quadrant-separator"></div>
                        <div class="odontogram-quadrant" id="quad-lower-left">
                            ${TEETH.lower_left.map(t => OdontogramPage.renderTooth(t, 'lower')).join('')}
                            <span class="odontogram-arch-label" style="align-self:center;margin-left:.5rem;font-size:.7rem;">Izquierda</span>
                        </div>
                    </div>
                    <div class="odontogram-arch-label">Inferior</div>
                </div>

                <!-- Legend -->
                <div class="odontogram-legend">
                    <div class="legend-item"><div class="legend-swatch" style="background:var(--odo-preexisting);"></div> Preexistente (rojo)</div>
                    <div class="legend-item"><div class="legend-swatch" style="background:var(--odo-treatment);"></div> Prestación nueva (azul)</div>
                    <div class="legend-item"><span style="font-weight:700;color:var(--odo-preexisting);">X</span> Extracción / Ausente</div>
                    <div class="legend-item"><span style="font-weight:700;">O</span> Caries</div>
                    <div class="legend-item"><span style="font-weight:700;">⌓</span> Corona</div>
                    <div class="legend-item"><span style="font-weight:700;">▭</span> Prót. Fija</div>
                    <div class="legend-item"><span style="font-weight:700;">▯</span> Prót. Removible</div>
                </div>
            </div>

            <!-- Entries Table -->
            <div class="card odontogram-entries">
                <div class="card-header">
                    <h2>Registro de Prestaciones</h2>
                    <button class="btn btn-sm btn-primary" onclick="OdontogramPage.showEntryForm()">+ Agregar Registro</button>
                </div>
                <div id="odo-entries-table" class="table-container">
                    <div class="empty-state">
                        <div class="empty-state-icon">🦷</div>
                        <div class="empty-state-text">Seleccioná un paciente</div>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Listen for patient change
    document.getElementById('odo-patient').addEventListener('change', (e) => {
        odontogramState.patientId = e.target.value || null;
        if (odontogramState.patientId) {
            const p = patients.find(p => p.id === odontogramState.patientId);
            document.getElementById('odo-insurance').textContent = p ? `Obra Social: ${p.insurance_name || 'Particular'}` : '';
            OdontogramPage.loadEntries();
        } else {
            OdontogramPage.clearChart();
        }
    });

    // Auto-load if patient was pre-selected
    if (storedPatientId) {
        odontogramState.patientId = storedPatientId;
        sessionStorage.removeItem('odontogram_patient_id');
        const p = patients.find(p => p.id === storedPatientId);
        if (p) document.getElementById('odo-insurance').textContent = `Obra Social: ${p.insurance_name || 'Particular'}`;
        OdontogramPage.loadEntries();
    }
});


const OdontogramPage = {
    renderTooth(number, position) {
        const isUpper = position === 'upper';
        return `
            <div class="tooth" id="tooth-${number}" data-tooth="${number}">
                ${isUpper ? `<div class="tooth-number">${number}</div>` : ''}
                <div class="tooth-diagram" id="diagram-${number}">
                    <div class="tooth-face tooth-face-vestibular" data-tooth="${number}" data-face="vestibular" onclick="OdontogramPage.clickFace(${number}, 'vestibular', this)"></div>
                    <div class="tooth-face tooth-face-mesial" data-tooth="${number}" data-face="mesial" onclick="OdontogramPage.clickFace(${number}, 'mesial', this)"></div>
                    <div class="tooth-face tooth-face-oclusal" data-tooth="${number}" data-face="oclusal" onclick="OdontogramPage.clickFace(${number}, 'oclusal', this)"></div>
                    <div class="tooth-face tooth-face-distal" data-tooth="${number}" data-face="distal" onclick="OdontogramPage.clickFace(${number}, 'distal', this)"></div>
                    <div class="tooth-face tooth-face-palatina" data-tooth="${number}" data-face="palatina" onclick="OdontogramPage.clickFace(${number}, 'palatina', this)"></div>
                    <div class="tooth-overlay" id="overlay-${number}"></div>
                </div>
                ${!isUpper ? `<div class="tooth-number">${number}</div>` : ''}
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
    },

    async clickFace(toothNumber, face, el) {
        if (!odontogramState.patientId) {
            UI.toast('Seleccioná un paciente primero', 'error');
            return;
        }

        const tool = odontogramState.selectedTool;
        const category = odontogramState.selectedCategory;

        // For whole-tooth symbols, apply to 'full'
        const fullToothSymbols = ['extraction', 'missing', 'crown', 'root_canal', 'fixed_prosthesis', 'removable_prosthesis', 'implant'];
        const effectiveFace = fullToothSymbols.includes(tool) ? 'full' : face;

        try {
            await API.createOdontogramEntry({
                patient_id: odontogramState.patientId,
                tooth_number: toothNumber,
                face: effectiveFace,
                symbol: tool,
                category: category,
            });
            UI.toast(`${SYMBOLS.find(s => s.id === tool).label} registrado en diente ${toothNumber}`, 'success');
            this.loadEntries();
        } catch (err) {
            UI.toast(err.message, 'error');
        }
    },

    async loadEntries() {
        if (!odontogramState.patientId) return;

        try {
            const entries = await API.getOdontogram(odontogramState.patientId);
            odontogramState.entries = entries;
            this.renderChart(entries);
            this.renderEntriesTable(entries);
        } catch (err) {
            UI.toast(err.message, 'error');
        }
    },

    renderChart(entries) {
        // Reset all faces
        document.querySelectorAll('.tooth-face').forEach(f => {
            f.classList.remove('preexisting', 'treatment');
        });
        document.querySelectorAll('.tooth-overlay').forEach(o => {
            o.textContent = '';
            o.className = 'tooth-overlay';
        });

        entries.forEach(e => {
            const colorClass = e.category === 'preexisting' ? 'preexisting' : 'treatment';

            if (e.face === 'full') {
                // Whole tooth operations
                const overlay = document.getElementById(`overlay-${e.tooth_number}`);
                if (overlay) {
                    const sym = SYMBOLS.find(s => s.id === e.symbol);
                    overlay.textContent = sym ? sym.icon : '';
                    overlay.classList.add(e.symbol);
                    overlay.style.color = e.category === 'preexisting' ? 'var(--odo-preexisting)' : 'var(--odo-treatment)';
                }
                // Also color all faces
                FACES.forEach(face => {
                    const faceEl = document.querySelector(`[data-tooth="${e.tooth_number}"][data-face="${face}"]`);
                    if (faceEl) faceEl.classList.add(colorClass);
                });
            } else {
                // Individual face
                const faceEl = document.querySelector(`[data-tooth="${e.tooth_number}"][data-face="${e.face}"]`);
                if (faceEl) faceEl.classList.add(colorClass);
            }
        });
    },

    renderEntriesTable(entries) {
        const container = document.getElementById('odo-entries-table');
        if (entries.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📋</div>
                    <div class="empty-state-text">Sin registros</div>
                    <div class="empty-state-sub">Hacé clic en un diente para agregar una prestación</div>
                </div>`;
            return;
        }

        const categories = { preexisting: '🔴 Preexistente', treatment: '🔵 Prestación' };
        const faceLabels = { mesial: 'Mesial', distal: 'Distal', vestibular: 'Vestibular', palatina: 'Palatina/Lingual', oclusal: 'Oclusal', full: 'Completo' };

        container.innerHTML = `
            <table>
                <thead>
                    <tr>
                        <th>Diente</th>
                        <th>Cara</th>
                        <th>Símbolo</th>
                        <th>Categoría</th>
                        <th>Código</th>
                        <th>Descripción</th>
                        <th>Conformidad</th>
                        <th>Fecha</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    ${entries.map(e => `
                        <tr>
                            <td><strong>${e.tooth_number}</strong></td>
                            <td>${faceLabels[e.face] || e.face}</td>
                            <td>${SYMBOLS.find(s => s.id === e.symbol)?.label || e.symbol}</td>
                            <td>${categories[e.category] || e.category}</td>
                            <td>${e.procedure_code || '-'}</td>
                            <td>${e.description || '-'}</td>
                            <td>${e.patient_consent ? '✅ Sí' : '❌ No'}</td>
                            <td>${UI.formatDate(e.created_at)}</td>
                            <td>
                                <button class="btn btn-sm btn-danger" onclick="OdontogramPage.deleteEntry('${e.id}')">✕</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    },

    clearChart() {
        document.querySelectorAll('.tooth-face').forEach(f => {
            f.classList.remove('preexisting', 'treatment');
        });
        document.querySelectorAll('.tooth-overlay').forEach(o => {
            o.textContent = '';
            o.className = 'tooth-overlay';
        });
        document.getElementById('odo-entries-table').innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🦷</div>
                <div class="empty-state-text">Seleccioná un paciente</div>
            </div>`;
    },

    async deleteEntry(id) {
        const ok = await UI.confirm('Eliminar Registro', '¿Eliminar este registro del odontograma?');
        if (ok) {
            try {
                await API.deleteOdontogramEntry(id);
                UI.toast('Registro eliminado', 'success');
                this.loadEntries();
            } catch (err) {
                UI.toast(err.message, 'error');
            }
        }
    },

    showEntryForm() {
        if (!odontogramState.patientId) {
            UI.toast('Seleccioná un paciente primero', 'error');
            return;
        }

        const allTeeth = [...TEETH.upper_right, ...TEETH.upper_left, ...TEETH.lower_right, ...TEETH.lower_left];

        const body = `
            <form id="form-odo-entry" class="form-grid">
                <div class="form-group">
                    <label>Diente Nº *</label>
                    <select name="tooth_number" required>
                        ${allTeeth.map(t => `<option value="${t}">${t}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>Cara *</label>
                    <select name="face" required>
                        <option value="oclusal">Oclusal</option>
                        <option value="mesial">Mesial</option>
                        <option value="distal">Distal</option>
                        <option value="vestibular">Vestibular</option>
                        <option value="palatina">Palatina/Lingual</option>
                        <option value="full">Completo</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Símbolo *</label>
                    <select name="symbol" required>
                        ${SYMBOLS.map(s => `<option value="${s.id}">${s.icon} ${s.label}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>Categoría *</label>
                    <select name="category" required>
                        <option value="preexisting">🔴 Preexistente</option>
                        <option value="treatment">🔵 Prestación nueva</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Código Prestación</label>
                    <input type="text" name="procedure_code" placeholder="Ej: 0216">
                </div>
                <div class="form-group">
                    <label>Matrícula Prof.</label>
                    <input type="text" name="description" placeholder="Matrícula/Descripción">
                </div>
                <div class="form-group">
                    <label style="display:flex;align-items:center;gap:.5rem;">
                        <input type="checkbox" name="patient_consent"> Conformidad del paciente
                    </label>
                </div>
            </form>
        `;
        const footer = `
            <button class="btn btn-secondary" onclick="UI.closeModal()">Cancelar</button>
            <button class="btn btn-primary" onclick="OdontogramPage.saveEntry()">Guardar</button>
        `;
        UI.showModal('Nuevo Registro Odontograma', body, footer);
    },

    async saveEntry() {
        const data = UI.getFormData('form-odo-entry');
        data.patient_id = odontogramState.patientId;
        data.tooth_number = parseInt(data.tooth_number);

        if (!data.tooth_number || !data.face || !data.symbol || !data.category) {
            UI.toast('Completá los campos obligatorios', 'error');
            return;
        }

        try {
            await API.createOdontogramEntry(data);
            UI.closeModal();
            UI.toast('Registro guardado', 'success');
            this.loadEntries();
        } catch (err) {
            UI.toast(err.message, 'error');
        }
    },
};
