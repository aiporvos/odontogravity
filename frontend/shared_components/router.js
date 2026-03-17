/**
 * SPA Router - Client-side page navigation without reloads
 */
const Router = {
    currentPage: null,
    pages: {},

    register(name, renderFn) {
        this.pages[name] = renderFn;
    },

    async navigate(page) {
        if (this.currentPage === page) return;
        this.currentPage = page;

        // Update nav
        document.querySelectorAll('.nav-item').forEach(el => {
            el.classList.toggle('active', el.dataset.page === page);
        });

        // Render page
        const container = document.getElementById('page-container');
        if (this.pages[page]) {
            container.innerHTML = '<div class="loading-page"><div class="spinner"></div></div>';
            try {
                await this.pages[page](container);
            } catch (err) {
                console.error(`Error rendering page ${page}:`, err);
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">⚠️</div>
                        <div class="empty-state-text">Error al cargar la página</div>
                        <div class="empty-state-sub">${err.message}</div>
                    </div>`;
            }
        } else {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">🚧</div>
                    <div class="empty-state-text">Página en construcción</div>
                </div>`;
        }

        // Update URL hash
        window.location.hash = page;
    },

    getPageFromHash() {
        const hash = window.location.hash.replace('#', '');
        return hash || 'dashboard';
    }
};
