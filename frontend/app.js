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
        btn.innerHTML = '<div class="spinner" style="width:18px;height:18px;border-width:2px;"></div>';

        try {
            await API.login(email, password);
            showApp();
        } catch (err) {
            loginError.textContent = err.message;
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<span>Iniciar Sesión</span>';
        }
    });

    // ── Show App ───────────────────────────────────────
    let _contadorDerivaciones = null;

    function showApp() {
        loginScreen.classList.add('hidden');
        appScreen.classList.remove('hidden');

        // El contador de derivaciones se mira aunque no estés parado en esa
        // pantalla: si no, nadie se entera de que hay un paciente esperando.
        //
        // Va acá y no en init(): antes del login la consulta devuelve 401,
        // API.request borra la sesión y recarga la página, y eso es un bucle
        // de recargas infinito. Se ve enseguida abriendo la app sin sesión.
        if (typeof DerivacionesPage !== 'undefined' && !_contadorDerivaciones) {
            DerivacionesPage.revisarPendientes();
            _contadorDerivaciones = setInterval(() => {
                if (!document.hidden && API.isAuthenticated()) {
                    DerivacionesPage.revisarPendientes();
                }
            }, 2 * 60 * 1000);
        }

        // Set user info
        const user = API.user;
        if (user) {
            document.getElementById('user-name').textContent = user.full_name;
            document.getElementById('user-role').textContent = user.role;
            document.getElementById('user-avatar').textContent = user.full_name.charAt(0).toUpperCase();

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
