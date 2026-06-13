/* Shell 2.0 navigation rail — delegates to existing app.js controls, adds no business logic. */
(() => {
    'use strict';

    function $(id) { return document.getElementById(id); }

    function clickIf(el) {
        if (el) el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    }

    function syncRailState() {
        const body = document.body;
        const setupBtn = $('rail-focus-setup');
        const libBtn = $('rail-focus-library');
        if (setupBtn) setupBtn.classList.toggle('active', body.classList.contains('content-collapsed'));
        if (libBtn) libBtn.classList.toggle('active', body.classList.contains('setup-collapsed'));
    }

    function init() {
        const setupBtn = $('rail-focus-setup');
        const libBtn = $('rail-focus-library');
        const monitorBtn = $('rail-monitor');

        // Focus = collapse the *other* panel (reuses app.js collapse logic);
        // clicking again restores the collapsed panel.
        if (setupBtn) setupBtn.addEventListener('click', () => {
            const body = document.body;
            if (body.classList.contains('content-collapsed')) {
                clickIf($('content-collapse-btn')); // restore library
            } else {
                if (body.classList.contains('setup-collapsed')) clickIf($('setup-collapse-btn'));
                clickIf($('content-collapse-btn'));
            }
            setTimeout(syncRailState, 50);
        });
        if (libBtn) libBtn.addEventListener('click', () => {
            const body = document.body;
            if (body.classList.contains('setup-collapsed')) {
                clickIf($('setup-collapse-btn')); // restore setup
            } else {
                if (body.classList.contains('content-collapsed')) clickIf($('content-collapse-btn'));
                clickIf($('setup-collapse-btn'));
            }
            setTimeout(syncRailState, 50);
        });
        if (monitorBtn) monitorBtn.addEventListener('click', () => {
            const toggle = document.querySelector('#career-monitor .monitor-handle');
            clickIf(toggle);
        });

        // keep rail state in sync when app.js collapse buttons are used directly
        const observer = new MutationObserver(syncRailState);
        observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
        syncRailState();

        // Library horizontal tabs (replaces accordion UX; app.js logic untouched)
        const tabsBar = $('lib-tabs');
        const contentPanel = $('content-panel');
        if (tabsBar && contentPanel) {
            const tabs = Array.from(tabsBar.querySelectorAll('.lib-tab'));
            const setTab = (name) => {
                contentPanel.setAttribute('data-active-lib', name);
                tabs.forEach(b => {
                    const on = b.dataset.libTarget === name;
                    b.classList.toggle('active', on);
                    b.setAttribute('aria-selected', String(on));
                });
                try { localStorage.setItem('libTab', name); } catch (e) {}
            };
            tabs.forEach(b => b.addEventListener('click', () => setTab(b.dataset.libTarget)));
            let saved = 'decks';
            try { saved = localStorage.getItem('libTab') || 'decks'; } catch (e) {}
            if (!tabs.some(b => b.dataset.libTarget === saved)) saved = 'decks';
            setTab(saved);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
