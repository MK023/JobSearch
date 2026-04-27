/**
 * Dashboard widgets — live updates via the shared SSE stream.
 *
 * Wired to the `app:realtime-tick` window event that notifications.js
 * dispatches after debouncing SSE notifications. On each tick we fetch
 * the snapshot endpoint (server-rendered partial HTML, cached 5 s) and
 * swap each widget's outerHTML in place. Polling at 60 s is the backup
 * for when SSE is blocked by a proxy or the tab missed an event.
 *
 * Why a single shared tick instead of a second EventSource:
 *   Each EventSource holds an open HTTP connection. notifications.js
 *   already maintains one — re-using it via a window event keeps the
 *   server connection budget at one per tab.
 */
(function () {
    'use strict';

    // Only run on the dashboard page — other pages don't have widgets to update.
    function isDashboardPage() {
        return window.location.pathname.replace(/\/$/, '') === '';
    }

    if (!isDashboardPage()) return;

    const SNAPSHOT_URL = '/api/v1/dashboard/snapshot';
    const POLL_INTERVAL_MS = 60000;
    let inFlight = false;

    function applySnapshot(snapshot) {
        if (!snapshot || typeof snapshot !== 'object') return;
        Object.keys(snapshot).forEach(function (key) {
            const node = document.querySelector('[data-widget="' + key + '"]');
            const html = snapshot[key];
            if (!node || typeof html !== 'string') return;
            // outerHTML replaces the <section> entirely so the widget's
            // own attributes (data-widget, classes) come from the partial
            // — no drift between SSR and live rendering.
            node.outerHTML = html;
        });
    }

    function fetchSnapshot() {
        if (inFlight) return;
        inFlight = true;
        fetch(SNAPSHOT_URL, { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (data) applySnapshot(data);
            })
            .catch(function (e) {
                // Transient failures are absorbed — the next tick (SSE
                // or 60 s poll) will retry. Logged at debug to avoid
                // noise in DevTools console.
                console.debug('dashboard snapshot fetch failed:', e);
            })
            .finally(function () { inFlight = false; });
    }

    function startBackupPolling() {
        setInterval(function () {
            if (document.visibilityState === 'visible') fetchSnapshot();
        }, POLL_INTERVAL_MS);
    }

    function init() {
        window.addEventListener('app:realtime-tick', fetchSnapshot);
        startBackupPolling();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
