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

        watchForUpdates();
    }

    // ── Aviso de version nueva ─────────────────────────
    // El index.html se sirve con "no-store", asi que una recarga siempre trae la
    // ultima version. El problema es la pestania que queda abierta dias: no se
    // entera de que hubo deploy. Comparamos contra /api/version y avisamos.
    function watchForUpdates() {
        const loaded = window.APP_VERSION;
        if (!loaded) return; // servido fuera del backend (dev con file://, etc.)

        async function check() {
            try {
                const res = await fetch('/api/version', { cache: 'no-store' });
                if (!res.ok) return;
                const { version } = await res.json();
                if (version && version !== loaded) showUpdateBanner(version);
            } catch (_) {
                // Sin conexion: reintentamos en el proximo ciclo.
            }
        }

        setInterval(check, 5 * 60 * 1000);
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') check();
        });
    }

    function showUpdateBanner(version) {
        // Una sola vez por version: si el usuario lo cierra, no reaparece cada 5'.
        if (sessionStorage.getItem('dsp_update_notified') === version) return;
        sessionStorage.setItem('dsp_update_notified', version);

        const bar = document.createElement('div');
        bar.style.cssText = 'position:fixed;left:50%;transform:translateX(-50%);bottom:1.25rem;z-index:9999;display:flex;align-items:center;gap:.75rem;padding:.7rem 1rem;border-radius:var(--radius);background:var(--slate-800,#1e293b);color:#fff;box-shadow:0 8px 24px rgba(0,0,0,.25);font-size:.9rem;';
        bar.innerHTML = `
            <span>Hay una version nueva del sistema.</span>
            <button class="btn btn-primary" style="padding:.35rem .8rem;font-size:.85rem;">Actualizar</button>
            <button style="background:none;border:none;color:#cbd5e1;cursor:pointer;font-size:1.1rem;line-height:1;">&times;</button>
        `;
        const [reloadBtn, closeBtn] = bar.querySelectorAll('button');
        reloadBtn.addEventListener('click', () => window.location.reload());
        closeBtn.addEventListener('click', () => bar.remove());
        document.body.appendChild(bar);
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
    function showApp() {
        loginScreen.classList.add('hidden');
        appScreen.classList.remove('hidden');

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
    const omniboxInput = document.getElementById('omnibox-input');
    const omniboxResults = document.getElementById('omnibox-results');

    omniboxInput?.addEventListener('input', (e) => {
        clearTimeout(searchDebounce);
        const q = e.target.value.trim();
        if (q.length < 2) {
            omniboxResults.classList.remove('visible');
            return;
        }
        searchDebounce = setTimeout(async () => {
            try {
                const results = await API.search(q);
                if (results.length === 0) {
                    omniboxResults.innerHTML = `<div class="omnibox-result"><span style="color:var(--slate-400);">Sin resultados</span></div>`;
                } else {
                    omniboxResults.innerHTML = results.map(r => `
                        <div class="omnibox-result" onclick="App.goToResult('${r.type}', '${r.id}')">
                            <span class="result-type">${r.type === 'patient' ? 'Paciente' : 'Profesional'}</span>
                            <span class="result-label">${r.label}</span>
                            <span class="result-detail">${r.detail || ''}</span>
                        </div>
                    `).join('');
                }
                omniboxResults.classList.add('visible');
            } catch (err) {
                omniboxResults.classList.remove('visible');
            }
        }, 300);
    });

    // Close omnibox on click outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.omnibox')) {
            omniboxResults?.classList.remove('visible');
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
        goToResult(type, id) {
            omniboxResults.classList.remove('visible');
            omniboxInput.value = '';
            if (type === 'patient') {
                sessionStorage.setItem('odontogram_patient_id', id);
                Router.currentPage = null;
                Router.navigate('patients');
            }
        },
    };

    init();
})();
