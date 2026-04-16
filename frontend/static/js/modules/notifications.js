/**
 * Notification center: server-side dismiss via /api/v1/notifications/dismiss.
 *
 * All notifications are dismissible. Dismiss is persisted in the DB so
 * the sidebar badge stays in sync across tabs and page reloads.
 */

(function () {
    function updateBadgeCount(count) {
        var badge = document.querySelector('.sidebar-item[href="/notifications"] .sidebar-badge');
        if (count > 0) {
            if (!badge) {
                var link = document.querySelector('.sidebar-item[href="/notifications"]');
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
        var pill = document.querySelector('.page-header .pill-credit');
        if (pill) {
            pill.textContent = count > 0 ? count + ' attive' : 'Nessuna';
        }
    }

    function updateGroupVisibility() {
        document.querySelectorAll('.notification-group').forEach(function (group) {
            var visible = group.querySelectorAll('.notification-card:not([style*="display: none"])');
            group.style.display = visible.length === 0 ? 'none' : '';
        });
    }

    function updateEmptyState() {
        var anyVisible = document.querySelectorAll(
            '.notification-card:not([style*="display: none"])'
        ).length > 0;
        var emptyBlock = document.getElementById('notification-center-empty-after-dismiss');
        if (!anyVisible && !emptyBlock) {
            var container = document.querySelector('.content-inner');
            if (!container) return;
            container.appendChild(_buildEmptyBlock());
        } else if (anyVisible && emptyBlock) {
            emptyBlock.remove();
        }
    }

    function _buildEmptyBlock() {
        var wrap = document.createElement('div');
        wrap.id = 'notification-center-empty-after-dismiss';
        wrap.className = 'card card-mb';

        var inner = document.createElement('div');
        inner.className = 'notification-empty';

        var icon = document.createElement('div');
        icon.className = 'notification-empty-icon';
        icon.textContent = '\uD83D\uDC4C';

        var title = document.createElement('div');
        title.className = 'notification-empty-title';
        title.textContent = 'Tutto gestito';

        var body = document.createElement('div');
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

        var fd = new FormData();
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
            var btn = document.createElement('button');
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

    document.addEventListener('DOMContentLoaded', function () {
        wireDismissButtons();
    });
})();
