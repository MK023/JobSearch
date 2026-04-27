/**
 * Notification center client.
 *
 * Three responsibilities, one module:
 *
 * 1. Dismissal — explicit × button (wireDismissButtons) and implicit
 *    "seen-on-click" of the action link (wireActionLinks). Both persist
 *    in the DB so the sidebar badge stays in sync across tabs and reloads.
 *    The action-link path uses sendBeacon (or fetch keepalive) so the
 *    dismiss survives navigation, then hides the card instantly for
 *    visual feedback — important when target=_blank keeps the user on
 *    the current page.
 *
 * 2. Polling fallback (startPolling) — every POLL_INTERVAL_MS when the
 *    tab is visible, refetch notifications + sidebar counts. Pauses when
 *    the tab is hidden, resumes with an immediate fetch on visibilitychange.
 *    On the /notifications page, surfaces a "N nuove" banner instead of
 *    auto-reloading so the user is never disrupted mid-read.
 *
 * 3. SSE push (startSsePush) — subscribes to /api/v1/notifications/sse and
 *    refetches on every event (any name). Bursts are absorbed by a small
 *    debounce so 50 broadcasts in 1 s collapse to ~1 fetch, capped further
 *    by the server-side counts cache (5 s TTL).
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

    // --- Sidebar badge counts. One endpoint patches all four badges atomically. ---

    const SIDEBAR_BADGE_SELECTORS = {
        pending_count: '.sidebar-item[href="/history"]',
        agenda_count: '.sidebar-item[href="/agenda"]',
        interview_count: '.sidebar-item[href="/interviews"]',
        notification_count: '.sidebar-item[href="/notifications"]',
    };

    function _setSidebarBadge(linkSelector, count) {
        const link = document.querySelector(linkSelector);
        if (!link) return;
        let badge = link.querySelector('.sidebar-badge');
        if (count > 0) {
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'sidebar-badge';
                badge.setAttribute('aria-hidden', 'true');
                link.appendChild(badge);
            }
            badge.textContent = count < 10 ? String(count) : '9+';
        } else if (badge) {
            badge.remove();
        }
    }

    function _setAnalyticsDot(available) {
        const link = document.querySelector('.sidebar-item[href="/analytics"]');
        if (!link) return;
        let dot = link.querySelector('.sidebar-badge');
        if (available) {
            if (!dot) {
                dot = document.createElement('span');
                dot.className = 'sidebar-badge';
                dot.setAttribute('aria-label', 'Analytics sbloccata');
                dot.textContent = '•';
                link.appendChild(dot);
            }
        } else if (dot) {
            dot.remove();
        }
    }

    function fetchSidebarCounts() {
        fetch('/api/v1/notifications/sidebar-counts', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (!data) return;
                Object.keys(SIDEBAR_BADGE_SELECTORS).forEach(function (key) {
                    _setSidebarBadge(SIDEBAR_BADGE_SELECTORS[key], data[key] || 0);
                });
                _setAnalyticsDot(Boolean(data.analytics_available));
            })
            .catch(function (e) {
                console.debug('fetchSidebarCounts failed, will retry on next tick:', e);
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
        fetchSidebarCounts();
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

    // Debounced refresh — burst-mode imports (e.g. Chrome extension sending
    // 50 jobs in 2 s) emit one broadcast per item. Without debouncing the
    // client would issue 50 concurrent fetches; this collapses them into
    // ~1 fetch per debounce window. The server-side counts cache (5 s TTL)
    // adds a second layer of protection for Neon DB capacity.
    const REFRESH_DEBOUNCE_MS = 800;
    let refreshTimer = null;
    function scheduleRefresh() {
        if (refreshTimer) return;
        refreshTimer = setTimeout(function () {
            refreshTimer = null;
            pollNotifications();
            // Generic tick other realtime modules (dashboard widgets, …)
            // can subscribe to. Keeps a single EventSource shared across
            // the page instead of every module opening its own stream.
            window.dispatchEvent(new CustomEvent('app:realtime-tick'));
        }, REFRESH_DEBOUNCE_MS);
    }

    // SSE subscription. The server nudges every connected tab the moment an
    // event of interest happens (analysis:new, inbox:dedup, …). Listening
    // via onmessage catches every event name without the client having to
    // enumerate them — useful as the server adds new event types.
    function startSsePush() {
        if (typeof EventSource === 'undefined') {
            console.debug('[notifications] EventSource unsupported — SSE push disabled');
            return;
        }
        console.debug('[notifications] starting SSE subscriber');
        let source = null;
        const connect = function () {
            try {
                // withCredentials so the session cookie travels with the
                // stream — the endpoint requires an authenticated user.
                source = new EventSource('/api/v1/notifications/sse', { withCredentials: true });
            } catch (e) {
                console.debug('[notifications] EventSource ctor failed:', e);
                return;
            }
            source.onmessage = scheduleRefresh;
            source.addEventListener('analysis:new', scheduleRefresh);
            source.addEventListener('inbox:dedup', scheduleRefresh);
            source.onerror = function () {
                // Browser auto-retries after ~3 s by default; on fatal errors
                // (tab backgrounded and closed) it stops — that's fine.
                if (source && source.readyState === EventSource.CLOSED) {
                    setTimeout(connect, 5000);
                }
            };
        };
        connect();
    }

    // Defensive init: if notifications.js is loaded after DOMContentLoaded
    // already fired (race with async/defer in the future, or script reordering)
    // the addEventListener handler would never run. Check readyState and
    // dispatch directly when the DOM is already parsed.
    function init() {
        wireDismissButtons();
        wireActionLinks();
        startPolling();
        startSsePush();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
