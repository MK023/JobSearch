/**
 * Notification center: client-side dismiss for dismissible cards.
 *
 * Dismissed ids live in sessionStorage under NC_DISMISSED_KEY so they
 * reset on new tabs / sessions — sticky cards (critical/warning that
 * track actual app state) ignore the list by design.
 */

(function () {
    var NC_DISMISSED_KEY = 'nc:dismissed';

    function loadDismissed() {
        try {
            var raw = sessionStorage.getItem(NC_DISMISSED_KEY);
            if (!raw) return {};
            var parsed = JSON.parse(raw);
            return (parsed && typeof parsed === 'object') ? parsed : {};
        } catch (_) {
            return {};
        }
    }

    function persistDismissed(map) {
        try {
            sessionStorage.setItem(NC_DISMISSED_KEY, JSON.stringify(map));
        } catch (_) {
            // Private mode: fail silently. Acceptable degradation.
        }
    }

    function applyDismissed() {
        var dismissed = loadDismissed();
        var cards = document.querySelectorAll('.notification-card[data-notification-dismissible="1"]');
        cards.forEach(function (card) {
            var id = card.getAttribute('data-notification-id');
            if (id && dismissed[id]) {
                card.style.display = 'none';
            }
        });
        updateGroupVisibility();
        updateEmptyState();
    }

    function updateGroupVisibility() {
        document.querySelectorAll('.notification-group').forEach(function (group) {
            var visible = group.querySelectorAll('.notification-card:not([style*="display: none"])');
            group.style.display = visible.length === 0 ? 'none' : '';
        });
    }

    function _buildDismissedEmptyBlock() {
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
        title.textContent = 'Tutto archiviato per questa sessione';

        var body = document.createElement('div');
        body.className = 'notification-empty-body';
        body.textContent = 'Le card ignorate tornano alla prossima sessione, se ancora pertinenti.';

        inner.appendChild(icon);
        inner.appendChild(title);
        inner.appendChild(body);
        wrap.appendChild(inner);
        return wrap;
    }

    function updateEmptyState() {
        var anyVisible = document.querySelectorAll(
            '.notification-card:not([style*="display: none"])'
        ).length > 0;
        var emptyBlock = document.getElementById('notification-center-empty-after-dismiss');
        if (!anyVisible && !emptyBlock) {
            var groupsContainer = document.querySelector('.content-inner');
            if (!groupsContainer) return;
            groupsContainer.appendChild(_buildDismissedEmptyBlock());
        }
    }

    function dismissCard(id, cardEl) {
        if (!id) return;
        var dismissed = loadDismissed();
        dismissed[id] = Date.now();
        persistDismissed(dismissed);
        cardEl.style.transition = 'opacity 0.15s';
        cardEl.style.opacity = '0';
        setTimeout(function () {
            cardEl.style.display = 'none';
            updateGroupVisibility();
            updateEmptyState();
        }, 150);
    }

    function wireDismissButtons() {
        var cards = document.querySelectorAll('.notification-card[data-notification-dismissible="1"]');
        cards.forEach(function (card) {
            if (card.querySelector('.notification-card-dismiss')) return;
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'notification-card-dismiss';
            btn.setAttribute('aria-label', 'Ignora per questa sessione');
            btn.title = 'Ignora per questa sessione';
            btn.textContent = '\u00d7';
            btn.onclick = function () {
                dismissCard(card.getAttribute('data-notification-id'), card);
            };
            card.appendChild(btn);
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        wireDismissButtons();
        applyDismissed();
    });
})();
