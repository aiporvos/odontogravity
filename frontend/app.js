/**
 * Silprodent - SPA Main App Controller
 */
(function () {
    'use strict';

    const loginScreen = document.getElementById('login-screen');
    const appScreen = document.getElementById('app');
    const loginForm = document.getElementById('login-form');
    const loginError = document.getElementById('login-error');

    // ── Init ───────────────────────────────────────────
    function init() {
        if (API.isAuthenticated()) {
            showApp();
        }

        // Update topbar date
        const dateEl = document.getElementById('topbar-date');
        if (dateEl) {
            const now = new Date();
            dateEl.textContent = now.toLocaleDateString('es-AR', {
                weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
            });
        }
    }

    // ── Login ──────────────────────────────────────────
    loginForm?.addEventListener('submit', async (e) => {
        e.preventDefault();
        loginError.textContent = '';
        const email = document.getElementById('login-email').value;
        const password = document.getElementById('login-password').value;
        const btn = document.getElementById('login-btn');
        btn.disabled = true;
        const btnHtml = btn.innerHTML;
        btn.innerHTML = '<div class="spinner" style="width:20px;height:20px;border-width:2px;"></div><span>Ingresando…</span>';

        try {
            await API.login(email, password);
            showApp();
        } catch (err) {
            loginError.textContent = err.message;
            document.getElementById('login-password').select();
        } finally {
            btn.disabled = false;
            btn.innerHTML = btnHtml;
        }
    });


    // ── Detalles del login ────────────────────────────
    (function loginDetalles() {
        const h = new Date().getHours();
        const saludo = h >= 5 && h < 13 ? 'Buen día' : h >= 13 && h < 20 ? 'Buenas tardes' : 'Buenas noches';
        const greet = document.getElementById('login-greeting');
        if (greet) greet.textContent = saludo;
        const year = document.getElementById('login-year');
        if (year) year.textContent = new Date().getFullYear();

        const pass = document.getElementById('login-password');
        const toggle = document.getElementById('login-toggle-pass');
        const ojoAbierto = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
        const ojoCerrado = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.6 5.1A10.8 10.8 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-2.8 3.8M6.6 6.6A17.4 17.4 0 0 0 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2M2 2l20 20"/></svg>';
        toggle?.addEventListener('click', () => {
            const mostrar = pass.type === 'password';
            pass.type = mostrar ? 'text' : 'password';
            toggle.innerHTML = mostrar ? ojoCerrado : ojoAbierto;
            toggle.setAttribute('aria-pressed', String(mostrar));
            toggle.setAttribute('aria-label', mostrar ? 'Ocultar contraseña' : 'Mostrar contraseña');
            pass.focus();
        });

        const caps = document.getElementById('login-caps');
        const revisarMayus = (e) => {
            if (caps && e.getModifierState) caps.classList.toggle('visible', e.getModifierState('CapsLock'));
        };
        pass?.addEventListener('keydown', revisarMayus);
        pass?.addEventListener('keyup', revisarMayus);
        pass?.addEventListener('blur', () => caps?.classList.remove('visible'));
    })();

    // ── Show App ───────────────────────────────────────
    function showApp() {
        loginScreen.classList.add('hidden');
        appScreen.classList.remove('hidden');

        // Set user info
        const user = API.user;
        if (user) {
            document.getElementById('user-name').textContent = user.full_name;
            const roles = { admin: 'Administración', receptionist: 'Recepción', professional: 'Profesional' };
            document.getElementById('user-role').textContent = roles[user.role] || user.role;
            const inicial = (user.full_name || '').split(/\s+/)
                .find(p => p && !/^(dr|dra|od|lic)\.?$/i.test(p)) || user.full_name || '?';
            document.getElementById('user-avatar').textContent = inicial.charAt(0).toUpperCase();

            // Admin ve todo el menú de Administración.
            // Recepción ve solo "Configuración" (para encender/apagar el bot y los
            // números de notificación); Usuarios y Profesionales quedan ocultos.
            const isAdmin = user.role === 'admin';
            const isReception = user.role === 'receptionist';
            if (isAdmin || isReception) {
                document.getElementById('admin-nav').style.display = 'block';
                document.getElementById('nav-users').style.display = isAdmin ? '' : 'none';
                document.getElementById('nav-professionals').style.display = isAdmin ? '' : 'none';
            }
        }

        // Navigate to initial page
        const page = Router.getPageFromHash();
        Router.navigate(page);
    }

    // ── Sidebar Navigation ─────────────────────────────
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const page = item.dataset.page;
            if (page) Router.navigate(page);

            // Close sidebar on mobile
            document.getElementById('sidebar').classList.remove('open');
        });
    });

    // ── Mobile menu toggle ─────────────────────────────
    document.getElementById('btn-menu')?.addEventListener('click', () => {
        document.getElementById('sidebar').classList.toggle('open');
    });

    // ── Logout ─────────────────────────────────────────
    document.getElementById('btn-logout')?.addEventListener('click', () => {
        API.clearAuth();
        appScreen.classList.add('hidden');
        loginScreen.classList.remove('hidden');
        document.getElementById('admin-nav').style.display = 'none';
    });

    // ── Omnibox Search ─────────────────────────────────
    let searchDebounce;
    let omniboxIndex = -1;
    const omniboxInput = document.getElementById('omnibox-input');
    const omniboxResults = document.getElementById('omnibox-results');

    const omniboxItems = () =>
        [...(omniboxResults?.querySelectorAll('.omnibox-result[data-id]') || [])];

    const pintarOmniboxActivo = () => {
        const items = omniboxItems();
        items.forEach((el, i) => el.classList.toggle('activo', i === omniboxIndex));
        if (omniboxIndex >= 0 && items[omniboxIndex]) {
            items[omniboxIndex].scrollIntoView({ block: 'nearest' });
        }
    };

    omniboxInput?.addEventListener('input', (e) => {
        clearTimeout(searchDebounce);
        omniboxIndex = -1;
        const q = e.target.value.trim();
        if (q.length < 2) {
            omniboxResults.classList.remove('visible');
            return;
        }
        searchDebounce = setTimeout(async () => {
            try {
                const results = await API.search(q);
                omniboxIndex = -1;
                if (results.length === 0) {
                    omniboxResults.innerHTML = `<div class="omnibox-result"><span style="color:var(--slate-400);">Sin resultados</span></div>`;
                } else {
                    omniboxResults.innerHTML = results.map(r => `
                        <div class="omnibox-result" role="option" tabindex="-1"
                             data-type="${r.type}" data-id="${r.id}"
                             onclick="App.goToResult('${r.type}', '${r.id}')">
                            <span class="result-type">${r.type === 'patient' ? 'Paciente' : 'Profesional'}</span>
                            <span class="result-label">${UI.escape(r.label)}</span>
                            <span class="result-detail">${UI.escape(r.detail || '')}</span>
                        </div>
                    `).join('');
                }
                omniboxResults.classList.add('visible');
            } catch (err) {
                omniboxResults.classList.remove('visible');
            }
        }, 300);
    });

    // Flechas para recorrer resultados, Enter para abrir, Esc para cerrar.
    omniboxInput?.addEventListener('keydown', (e) => {
        if (!omniboxResults?.classList.contains('visible')) return;
        const items = omniboxItems();
        if (!items.length) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            omniboxIndex = Math.min(omniboxIndex + 1, items.length - 1);
            pintarOmniboxActivo();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            omniboxIndex = Math.max(omniboxIndex - 1, 0);
            pintarOmniboxActivo();
        } else if (e.key === 'Enter') {
            if (omniboxIndex < 0) return;
            e.preventDefault();
            const el = items[omniboxIndex];
            if (el) App.goToResult(el.dataset.type, el.dataset.id);
        } else if (e.key === 'Escape') {
            omniboxResults.classList.remove('visible');
            omniboxIndex = -1;
        }
    });

    // Close omnibox on click outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.omnibox')) {
            omniboxResults?.classList.remove('visible');
            omniboxIndex = -1;
        }
    });

    // ── FAB ────────────────────────────────────────────
    const fabMain = document.getElementById('fab-main');
    const fabMenu = document.getElementById('fab-menu');

    fabMain?.addEventListener('click', () => {
        fabMain.classList.toggle('open');
        fabMenu.classList.toggle('visible');
    });

    document.querySelectorAll('.fab-action').forEach(btn => {
        btn.addEventListener('click', () => {
            const action = btn.dataset.action;
            fabMain.classList.remove('open');
            fabMenu.classList.remove('visible');

            if (action === 'new-appointment') {
                AgendaPage.showNewAppointment();
            } else if (action === 'new-patient') {
                PatientsPage.showForm();
            }
        });
    });

    // ── Hash change ────────────────────────────────────
    window.addEventListener('hashchange', () => {
        if (API.isAuthenticated()) {
            const page = Router.getPageFromHash();
            Router.navigate(page);
        }
    });

    // ── Global App Object ──────────────────────────────
    window.App = {
        async goToResult(type, id) {
            omniboxResults.classList.remove('visible');
            omniboxInput.value = '';
            omniboxIndex = -1;

            // Antes el resultado se tocaba y no pasaba nada visible: guardaba el
            // id en la clave que usa el odontograma y redibujaba la lista entera
            // de pacientes, sin abrir ni resaltar al que se habia buscado.
            //
            // El await importa: navigate() cierra cualquier modal al entrar, asi
            // que la ficha se abre recien cuando la pagina termino de renderizar.
            if (type === 'patient') {
                await Router.navigate('patients');
                PatientsPage.showDesdeBusqueda(id);
            } else if (type === 'professional') {
                await Router.navigate('professionals');
            }
        },
    };

    init();
})();
