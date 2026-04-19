/**
 * Notification center: server-side dismiss via /api/v1/notifications/dismiss.
 *
 * Two dismiss paths — both persist in the DB so the sidebar badge stays in
 * sync across tabs and page reloads.
 *
 * 1. Explicit × button on each card (wireDismissButtons).
 * 2. Implicit "seen" via action-link click (wireActionLinks): clicking the
 *    primary CTA of a dismissible notification fires a sendBeacon/fetch
 *    keepalive dismiss, then lets the browser navigate. The card is hidden
 *    instantly for visual feedback — important when target=_blank keeps
 *    the user on the current page.
 *
 * Plus a lightweight polling loop (startPolling):
 *
 * - Every POLL_INTERVAL_MS when the tab is visible, fetch /api/v1/notifications
 * - Update sidebar badge + pill count immediately
 * - On the /notifications page specifically, show a "N nuove" banner when
 *   new notification IDs appear — click to reload. Never auto-reload to
 *   avoid disrupting the user mid-read.
 * - Pause when the tab is hidden; resume + immediate poll on visibilityhange.
 */

(function () {
    function updateBadgeCount(count) {
        let badge = document.querySelector('.sidebar-item[href="/notifications"] .sidebar-badge');
        if (count > 0) {
            if (!badge) {
                const link = document.querySelector('.sidebar-item[href="/notifications"]');
                if (link) {
                    badge = document.createElement('span');
                    badge.className = 'sidebar-badge';
                    link.appendChild(badge);
                }
            }
            if (badge) {
                badge.textContent = count < 10 ? count : '9+';
                badge.setAttribute('aria-label', count + ' notifiche');
            }
        } else if (badge) {
            badge.remove();
        }
    }

    function updatePillCount(count) {
        const pill = document.querySelector('.page-header .pill-credit');
        if (pill) {
            pill.textContent = count > 0 ? count + ' attive' : 'Nessuna';
        }
    }

    function updateGroupVisibility() {
        document.querySelectorAll('.notification-group').forEach(function (group) {
            const visible = group.querySelectorAll('.notification-card:not([style*="display: none"])');
            group.style.display = visible.length === 0 ? 'none' : '';
        });
    }

    function updateEmptyState() {
        const anyVisible = document.querySelectorAll(
            '.notification-card:not([style*="display: none"])'
        ).length > 0;
        const emptyBlock = document.getElementById('notification-center-empty-after-dismiss');
        if (!anyVisible && !emptyBlock) {
            const container = document.querySelector('.content-inner');
            if (!container) return;
            container.appendChild(_buildEmptyBlock());
        } else if (anyVisible && emptyBlock) {
            emptyBlock.remove();
        }
    }

    function _buildEmptyBlock() {
        const wrap = document.createElement('div');
        wrap.id = 'notification-center-empty-after-dismiss';
        wrap.className = 'card card-mb';

        const inner = document.createElement('div');
        inner.className = 'notification-empty';

        const icon = document.createElement('div');
        icon.className = 'notification-empty-icon';
        icon.textContent = '\uD83D\uDC4C';

        const title = document.createElement('div');
        title.className = 'notification-empty-title';
        title.textContent = 'Tutto gestito';

        const body = document.createElement('div');
        body.className = 'notification-empty-body';
        body.textContent = 'Le notifiche tornano quando cambia lo stato sottostante (nuovo colloquio, budget basso, ecc.).';

        inner.appendChild(icon);
        inner.appendChild(title);
        inner.appendChild(body);
        wrap.appendChild(inner);
        return wrap;
    }

    function dismissCard(notificationId, cardEl) {
        if (!notificationId) return;

        const fd = new FormData();
        fd.append('notification_id', notificationId);

        fetch('/api/v1/notifications/dismiss', { method: 'POST', body: fd })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.ok) {
                    cardEl.style.transition = 'opacity 0.15s';
                    cardEl.style.opacity = '0';
                    setTimeout(function () {
                        cardEl.style.display = 'none';
                        updateGroupVisibility();
                        updateEmptyState();
                    }, 150);
                    updateBadgeCount(data.remaining_count);
                    updatePillCount(data.remaining_count);
                }
            })
            .catch(function (e) {
                console.error('dismiss error:', e);
            });
    }

    function wireDismissButtons() {
        document.querySelectorAll('.notification-card').forEach(function (card) {
            if (card.querySelector('.notification-card-dismiss')) return;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'notification-card-dismiss';
            btn.setAttribute('aria-label', 'Ignora notifica');
            btn.title = 'Ignora notifica';
            btn.textContent = '\u00d7';
            btn.onclick = function () {
                dismissCard(card.getAttribute('data-notification-id'), card);
            };
            card.appendChild(btn);
        });
    }

    // Fire-and-forget dismiss on action-link click so the notification is
    // treated as "seen" once the user navigates to the destination. Uses
    // sendBeacon (or fetch keepalive) so the request survives page unload.
    function dismissBeacon(notificationId) {
        if (!notificationId) return;
        const fd = new FormData();
        fd.append('notification_id', notificationId);
        try {
            if (navigator.sendBeacon) {
                navigator.sendBeacon('/api/v1/notifications/dismiss', fd);
                return;
            }
        } catch (e) {
            // Beacon unavailable or quota exceeded — fall through to fetch keepalive.
            console.debug('sendBeacon dismiss failed, falling back to fetch:', e);
        }
        try {
            fetch('/api/v1/notifications/dismiss', {
                method: 'POST',
                body: fd,
                keepalive: true,
            });
        } catch (e) {
            // Dismiss is best-effort; never block navigation on failure.
            console.debug('fetch keepalive dismiss failed:', e);
        }
    }

    function wireActionLinks() {
        document.querySelectorAll('.notification-card .notification-card-actions a').forEach(function (link) {
            if (link.dataset.dismissOnClickWired === '1') return;
            link.dataset.dismissOnClickWired = '1';
            link.addEventListener('click', function () {
                const card = link.closest('.notification-card');
                if (!card) return;
                if (card.getAttribute('data-notification-dismissible') !== '1') return;
                const id = card.getAttribute('data-notification-id');
                dismissBeacon(id);
                // Instant visual feedback — survives target=_blank where the
                // user stays on the current page after opening a new tab.
                card.style.transition = 'opacity 0.15s';
                card.style.opacity = '0';
                setTimeout(function () {
                    card.style.display = 'none';
                    updateGroupVisibility();
                    updateEmptyState();
                }, 150);
            });
        });
    }

    // --- Polling: fresh notifications without manual reload. ---

    const POLL_INTERVAL_MS = 60000;
    let knownIds = null; // lazy-initialised from the DOM on first poll

    function isOnNotificationsPage() {
        return window.location.pathname.replace(/\/$/, '') === '/notifications';
    }

    function currentDomIds() {
        const ids = new Set();
        document.querySelectorAll('.notification-card').forEach(function (card) {
            const id = card.getAttribute('data-notification-id');
            if (id) ids.add(id);
        });
        return ids;
    }

    function showNewBanner(newCount) {
        const existing = document.getElementById('notification-fresh-banner');
        if (existing) {
            existing.textContent = newCount + (newCount === 1 ? ' nuova notifica' : ' nuove notifiche') +
                ' disponibil' + (newCount === 1 ? 'e' : 'i') + ' — click per aggiornare';
            return;
        }
        const btn = document.createElement('button');
        btn.id = 'notification-fresh-banner';
        btn.type = 'button';
        btn.className = 'notification-fresh-banner';
        btn.textContent = newCount + (newCount === 1 ? ' nuova notifica' : ' nuove notifiche') +
            ' disponibil' + (newCount === 1 ? 'e' : 'i') + ' — click per aggiornare';
        btn.addEventListener('click', function () { window.location.reload(); });

        const container = document.querySelector('.content-inner');
        if (container) container.insertBefore(btn, container.firstChild);
    }

    function pollNotifications() {
        fetch('/api/v1/notifications', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (list) {
                if (!Array.isArray(list)) return;
                const ids = new Set(list.map(function (n) { return n.id; }));
                updateBadgeCount(ids.size);
                updatePillCount(ids.size);

                if (isOnNotificationsPage()) {
                    if (knownIds === null) {
                        knownIds = currentDomIds();
                    }
                    let added = 0;
                    ids.forEach(function (id) { if (!knownIds.has(id)) added++; });
                    if (added > 0) showNewBanner(added);
                }
            })
            .catch(function (e) {
                // Network hiccup — the poller retries on the next interval tick,
                // so swallowing here is intentional.
                console.debug('pollNotifications failed, will retry:', e);
            });
    }

    function startPolling() {
        if (isOnNotificationsPage()) knownIds = currentDomIds();
        setInterval(function () {
            if (document.visibilityState === 'visible') pollNotifications();
        }, POLL_INTERVAL_MS);
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'visible') pollNotifications();
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        wireDismissButtons();
        wireActionLinks();
        startPolling();
    });
})();
