/**
 * Dental Studio Pro - SPA Main App Controller
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
    function showApp() {
        loginScreen.classList.add('hidden');
        appScreen.classList.remove('hidden');

        // Set user info
        const user = API.user;
        if (user) {
            document.getElementById('user-name').textContent = user.full_name;
            document.getElementById('user-role').textContent = user.role;
            document.getElementById('user-avatar').textContent = user.full_name.charAt(0).toUpperCase();

            // Show admin nav for admins
            if (user.role === 'admin') {
                document.getElementById('admin-nav').style.display = 'block';
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
