/**
 * Shared UI Components - Modal, Toast, Helpers
 */
const UI = {
    // ── Modal ──────────────────────────────────────────
    showModal(title, bodyHtml, footerHtml = '') {
        document.getElementById('modal-title').textContent = title;
        document.getElementById('modal-body').innerHTML = bodyHtml;
        const footer = document.getElementById('modal-footer');
        footer.innerHTML = footerHtml;
        footer.classList.toggle('hidden', !footerHtml);
        document.getElementById('modal-overlay').classList.remove('hidden');
    },

    modal(html, title = 'Información') {
        this.showModal(title, html, '');
    },

    // `respuestaDelConfirm` solo importa cuando el modal abierto es un
    // UI.confirm(): es lo que se le devuelve a quien esta esperando la
    // respuesta. Cerrar sin elegir vale "no".
    closeModal(respuestaDelConfirm = false) {
        document.getElementById('modal-overlay').classList.add('hidden');
        document.getElementById('modal-body').innerHTML = '';
        document.getElementById('modal-footer').innerHTML = '';

        // Un confirm() cerrado con Escape, con la ×, clickeando el fondo o
        // navegando a otra pantalla dejaba su promesa colgada para siempre, y
        // el codigo que la esperaba no seguia nunca. Ahora siempre se resuelve.
        const pendiente = window._confirmResolve;
        window._confirmResolve = null;
        if (pendiente) pendiente(respuestaDelConfirm === true);

        // Lo mismo para elegir(): cerrar sin elegir devuelve null en vez de
        // dejar esperando para siempre a quien llamo.
        const eleccion = window._eleccionResolve;
        window._eleccionResolve = null;
        if (eleccion) eleccion(null);
    },

    modalAbierto() {
        const overlay = document.getElementById('modal-overlay');
        return !!overlay && !overlay.classList.contains('hidden');
    },

    // ── Toast ──────────────────────────────────────────
    toast(message, type = 'info') {
        const icons = { success: '✅', error: '❌', info: 'ℹ️' };
        const container = document.getElementById('toast-container');
        const el = document.createElement('div');
        el.className = `toast toast-${type}`;
        el.innerHTML = `<span>${icons[type] || ''}</span><span>${message}</span>`;
        container.appendChild(el);
        setTimeout(() => el.remove(), 4000);
    },

    // ── Confirm ────────────────────────────────────────
    confirm(title, message = '') {
        return new Promise((resolve) => {
            // Si no se pasa mensaje, no renderizamos el párrafo (evita mostrar "undefined").
            const body = message
                ? `<p style="color:var(--slate-600);font-size:.95rem;">${message}</p>`
                : '';
            const footer = `
                <button class="btn btn-secondary" onclick="UI.closeModal(false)">Cancelar</button>
                <button class="btn btn-danger" onclick="UI.closeModal(true)">Confirmar</button>
            `;
            window._confirmResolve = resolve;
            this.showModal(title, body, footer);
        });
    },

    // ── Format Helpers ─────────────────────────────────
    formatDate(dateStr) {
        if (!dateStr) return '-';
        const d = new Date(dateStr);
        return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
    },

    formatTime(dateStr) {
        if (!dateStr) return '-';
        const d = new Date(dateStr);
        return d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
    },

    formatDateTime(dateStr) {
        if (!dateStr) return '-';
        return `${this.formatDate(dateStr)} ${this.formatTime(dateStr)}`;
    },

    statusBadge(status) {
        const labels = {
            pending: 'Pendiente', confirmed: 'Confirmado',
            completed: 'Realizado', cancelled: 'Cancelado', no_show: 'No asistió',
        };
        return `<span class="badge badge-${status}">${labels[status] || status}</span>`;
    },

    channelLabel(channel) {
        const labels = {
            web: '🌐 Web', bot_whatsapp: '📱 WhatsApp',
            bot_telegram: '💬 Telegram', phone: '📞 Teléfono',
        };
        return labels[channel] || channel;
    },

    // Como confirm(), pero con las opciones que haga falta. Nace del aviso de
    // paciente repetido, donde "sí/no" no alcanza: la respuesta util casi
    // siempre es una tercera, "usá la ficha que ya existe".
    //
    // `opciones` es [{valor, texto, clase}]. Cerrar sin elegir devuelve null.
    elegir(titulo, cuerpoHtml, opciones) {
        return new Promise((resolve) => {
            // Una opcion con `oculta` no sale como boton del pie, pero se puede
            // elegir desde el cuerpo con UI._responderEleccion(i). Sirve para
            // que cada ficha repetida sea clickeable en la lista.
            const footer = opciones.map((o, i) => o.oculta ? '' :
                `<button class="btn ${o.clase || 'btn-secondary'}" onclick="UI._responderEleccion(${i})">${UI.escape(o.texto)}</button>`
            ).join('');
            window._eleccionResolve = (i) => resolve(i === null ? null : opciones[i].valor);
            this.showModal(titulo, cuerpoHtml, footer);
        });
    },

    _responderEleccion(i) {
        const pendiente = window._eleccionResolve;
        window._eleccionResolve = null;
        this.closeModal();
        if (pendiente) pendiente(i);
    },

    // El aviso de ficha repetida. Devuelve el id de la ficha a usar, 'crear'
    // si de verdad es otra persona, o null si se cierra sin decidir.
    //
    // Muestra los datos de las fichas que ya estan (DNI, telefono, cuantos
    // turnos) porque con el nombre solo no se puede decidir si es la misma
    // persona o un homonimo.
    async fichaRepetida(err, quien) {
        const fichas = err.yaExisten || [];

        // Cada ficha es una opcion clickeable. Con dos o mas repetidas hay que
        // poder decir CUAL usar, no solo "usá la que existe".
        const opciones = fichas.map(p => ({ valor: p.id, oculta: true }));
        const iCancelar = opciones.push({ valor: null, texto: 'Cancelar' }) - 1;
        const iCrear = opciones.push({
            valor: 'crear', texto: 'Es otro, crear igual', clase: 'btn-danger',
        }) - 1;

        const filas = fichas.map((p, i) => `
            <div class="ficha-repetida" onclick="UI._responderEleccion(${i})">
                <div>
                    <strong>${UI.escape(p.last_name)}, ${UI.escape(p.first_name)}</strong>
                    <div style="font-size:.82rem;opacity:.75;margin-top:.15rem;">
                        ${p.dni ? 'DNI ' + UI.escape(p.dni) : 'sin DNI'} ·
                        ${p.phone ? UI.escape(p.phone) : 'sin teléfono'} ·
                        ${p.turnos} turno${p.turnos === 1 ? '' : 's'}
                        ${p.insurance_name ? ' · ' + UI.escape(p.insurance_name) : ''}
                    </div>
                </div>
                <span style="font-size:.8rem;font-weight:700;white-space:nowrap;">Usar esta →</span>
            </div>`).join('');

        const cuerpo = `
            <p style="margin:0 0 .6rem;">${UI.escape(err.message)}</p>
            ${filas}
            <p style="font-size:.85rem;color:var(--slate-500);margin:.6rem 0 0;">
                Si es la misma persona, tocá su ficha: una ficha repetida parte la
                historia clínica en dos. Si de verdad es otro paciente que se llama
                igual, creala igual.
            </p>`;

        void iCancelar; void iCrear;
        return this.elegir(`¿Es el mismo ${quien || 'paciente'}?`, cuerpo, opciones);
    },

    // Un apellido con < o & no puede romper el HTML donde se lo dibuja.
    escape(txt) {
        return String(txt ?? '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    },

    // ── Tablas ─────────────────────────────────────────
    // Tabla con orden por columna y paginado. Todas las tablas del panel
    // volcaban la lista entera de una: con 475 pacientes cargados eso es una
    // pantalla imposible de recorrer, y sin forma de ordenarla por nada.
    //
    //   UI.tabla('patients-table', {
    //       filas: patients,
    //       columnas: [
    //           {titulo: 'Apellido, Nombre', valor: p => `${p.last_name}, ${p.first_name}`},
    //           {titulo: 'DNI', valor: p => p.dni, html: p => p.dni || '—'},
    //           {titulo: 'Acciones', orden: false, html: p => `<button ...>`},
    //       ],
    //       vacio: 'No se encontraron pacientes',
    //   });
    //
    // `valor` es lo que se usa para ordenar y, si no hay `html`, lo que se
    // muestra. `html` va tal cual: si viene de datos del usuario, escapalo.
    _tablas: {},

    tabla(contenedorId, config) {
        const cont = document.getElementById(contenedorId);
        if (!cont) return;

        // El orden y la pagina sobreviven a un redibujado: si no, ordenar por
        // una columna y que un refresco te devuelva al orden original es peor
        // que no poder ordenar.
        const estado = this._tablas[contenedorId] || (this._tablas[contenedorId] = {
            columna: null, descendente: false, pagina: 1,
        });
        if (config) estado.config = config;
        const { columnas, filas, vacio, porPagina = 25 } = estado.config;

        if (!filas.length) {
            cont.innerHTML = `<div class="empty-state"><div class="empty-state-text">${vacio || 'No hay datos'}</div></div>`;
            return;
        }

        // ── Ordenar ──
        const ordenadas = [...filas];
        if (estado.columna !== null && columnas[estado.columna]) {
            const col = columnas[estado.columna];
            const signo = estado.descendente ? -1 : 1;
            ordenadas.sort((a, b) => {
                const va = col.valor(a), vb = col.valor(b);
                // Los vacios van al final SIEMPRE, en los dos sentidos: una
                // ficha sin DNI no es "la que tiene el DNI mas alto". Por eso
                // se resuelve antes de aplicar el signo.
                const ea = this._celdaVacia(va), eb = this._celdaVacia(vb);
                if (ea || eb) return ea && eb ? 0 : (ea ? 1 : -1);
                return signo * this._compararCeldas(va, vb);
            });
        }

        // ── Paginar ──
        const paginas = Math.max(1, Math.ceil(ordenadas.length / porPagina));
        estado.pagina = Math.min(Math.max(1, estado.pagina), paginas);
        const desde = (estado.pagina - 1) * porPagina;
        const visibles = ordenadas.slice(desde, desde + porPagina);

        const encabezados = columnas.map((c, i) => {
            if (c.orden === false) return `<th>${c.titulo}</th>`;
            const activa = estado.columna === i;
            const flecha = activa ? (estado.descendente ? ' ▼' : ' ▲') : '';
            return `<th class="th-ordenable${activa ? ' activa' : ''}"
                        onclick="UI._ordenarTabla('${contenedorId}', ${i})"
                        title="Ordenar por ${c.titulo}">${c.titulo}${flecha}</th>`;
        }).join('');

        // `filaAttrs` deja poner clase, ondblclick o title en el <tr>: hay tablas
        // que colorean la fila entera o reaccionan al doble clic.
        const attrs = estado.config.filaAttrs || (() => '');
        const cuerpo = visibles.map(f => `<tr ${attrs(f)}>${
            columnas.map(c => `<td${c.tdAttrs ? ' ' + c.tdAttrs(f) : ''}>${
                c.html ? c.html(f) : UI.escape(c.valor(f) ?? '')
            }</td>`).join('')
        }</tr>`).join('');

        cont.innerHTML = `
            <table><thead><tr>${encabezados}</tr></thead><tbody>${cuerpo}</tbody></table>
            ${this._pieDeTabla(contenedorId, estado.pagina, paginas, desde, visibles.length, ordenadas.length)}`;
    },

    _pieDeTabla(contenedorId, pagina, paginas, desde, cuantas, total) {
        if (paginas <= 1) {
            return `<div class="tabla-pie"><span>${total} registro${total === 1 ? '' : 's'}</span></div>`;
        }
        const ir = (n, texto, deshabilitado = false) =>
            `<button class="tabla-pag${n === pagina ? ' activa' : ''}" ${deshabilitado ? 'disabled' : ''}
                     onclick="UI._irAPagina('${contenedorId}', ${n})">${texto}</button>`;

        // Una ventana de paginas alrededor de la actual: con 20 paginas no
        // entran todas, y el usuario igual navega de a poco.
        const desdeN = Math.max(1, Math.min(pagina - 2, paginas - 4));
        const hastaN = Math.min(paginas, Math.max(pagina + 2, 5));
        const numeros = [];
        for (let n = desdeN; n <= hastaN; n++) numeros.push(ir(n, n));

        return `
            <div class="tabla-pie">
                <span>${desde + 1}–${desde + cuantas} de ${total}</span>
                <div class="tabla-paginas">
                    ${ir(pagina - 1, '‹', pagina === 1)}
                    ${desdeN > 1 ? ir(1, '1') + '<span class="tabla-puntos">…</span>' : ''}
                    ${numeros.join('')}
                    ${hastaN < paginas ? '<span class="tabla-puntos">…</span>' + ir(paginas, paginas) : ''}
                    ${ir(pagina + 1, '›', pagina === paginas)}
                </div>
            </div>`;
    },

    _celdaVacia(v) {
        return v === null || v === undefined || v === '' ||
               (typeof v === 'string' && v.trim() === '');
    },

    // Números como números y fechas como fechas: ordenar "10" y "9" como texto
    // deja el 10 antes que el 9.
    _compararCeldas(a, b) {
        if (typeof a === 'number' && typeof b === 'number') return a - b;
        if (a instanceof Date && b instanceof Date) return a - b;

        const na = Number(a), nb = Number(b);
        if (!Number.isNaN(na) && !Number.isNaN(nb) && String(a).trim() !== '' && String(b).trim() !== '') {
            return na - nb;
        }
        return String(a).localeCompare(String(b), 'es', { sensitivity: 'base', numeric: true });
    },

    _ordenarTabla(contenedorId, i) {
        const estado = this._tablas[contenedorId];
        if (!estado) return;
        // Tocar la misma columna alterna ascendente/descendente.
        if (estado.columna === i) estado.descendente = !estado.descendente;
        else { estado.columna = i; estado.descendente = false; }
        estado.pagina = 1;
        this.tabla(contenedorId, null);
    },

    _irAPagina(contenedorId, n) {
        const estado = this._tablas[contenedorId];
        if (!estado) return;
        estado.pagina = n;
        this.tabla(contenedorId, null);
        document.getElementById(contenedorId)?.scrollIntoView({ block: 'nearest' });
    },

    // ── Form Helpers ───────────────────────────────────
    getFormData(formId) {
        const form = document.getElementById(formId);
        if (!form) return {};
        const data = {};
        const inputs = form.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
            if (input.name) {
                if (input.type === 'checkbox') {
                    data[input.name] = input.checked;
                } else if (input.type === 'number') {
                    data[input.name] = input.value === '' ? null : Number(input.value);
                } else {
                    data[input.name] = input.value;
                }
            }
        });
        return data;
    },

    // ── Date ──
    todayISO() {
        return new Date().toISOString().split('T')[0];
    },

    nowISO() {
        const d = new Date();
        d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
        return d.toISOString().slice(0, 16);
    },
};

// Close modal listeners
document.getElementById('modal-close')?.addEventListener('click', () => UI.closeModal());
document.getElementById('modal-overlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'modal-overlay') UI.closeModal();
});

// Escape cierra el modal. Es lo que espera cualquiera que haya usado una
// ventana modal antes, y hasta ahora la unica salida era apuntarle a la × o al
// borde. Un control de adentro que ya use Escape para lo suyo (el desplegable
// del buscador de pacientes, por ejemplo) frena el evento antes de que llegue
// hasta aca, asi que el primer Escape cierra la lista y el segundo el modal.
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && UI.modalAbierto()) UI.closeModal();
});
