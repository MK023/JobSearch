/**
 * Main Alpine.js root component and application initializer.
 *
 * Module scripts are loaded per-page via {% block scripts_extra %}.
 * This file provides the root Alpine component used by base.html:
 *   <body x-data="app()" x-init="init()">
 *
 * Available modules (only present if their <script> tag is on this page):
 *   - spending.js   -> initBudgetEditing(), refreshSpending()
 *   - history.js    -> historyTabs(), refreshHistoryCounts()
 *   - status.js     -> setStatus(), deleteAnalysis()
 *   - batch.js      -> batchManager()
 *   - contacts.js   -> toggleContacts(), loadContacts(), saveContact(), deleteContact()
 *   - followup.js   -> genFollowup(), genLinkedin(), markFollowupDone()
 *   - cv.js         -> uploadCV(), initCVUpload()
 *   - toast.js      -> showToast()
 */

function app() {
    return {
        analyzeLoading: false,
        coverLetterLoading: false,

        init: function() {
            // Only init modules that are present on this page
            if (typeof initBudgetEditing === 'function') initBudgetEditing();
            if (typeof initCVUpload === 'function') initCVUpload();

            // No periodic polling: the dashboard is fully SSR, event-driven refresh only.
            // Upcoming interviews live in the notification center; spending updates on
            // successful analyze / cover-letter calls via refreshSpending() call sites.

            // Check for background analysis completion
            _checkPendingAnalysis();
        }
    };
}


/**
 * Toggle between dark and light themes.
 * Persists choice in localStorage. Default is dark.
 */
function toggleTheme() {
    var html = document.documentElement;
    var current = html.getAttribute('data-theme') || 'dark';
    var next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
}


/**
 * Check if a background analysis completed while user was on another page.
 * Polls /api/v1/analysis/latest and shows a banner if new analysis found.
 * Shows error banner after 90s if analysis never completes.
 */
function _checkPendingAnalysis() {
    var raw = sessionStorage.getItem('pendingAnalysis');
    if (!raw) return;

    var pending;
    try { pending = JSON.parse(raw); } catch (_) { sessionStorage.removeItem('pendingAnalysis'); return; }

    var startedAt = new Date(pending.startedAt).getTime();
    var elapsed = Date.now() - startedAt;

    if (elapsed > 300000) {
        sessionStorage.removeItem('pendingAnalysis');
        return;
    }

    function poll() {
        fetch('/api/v1/analysis/latest', { headers: { 'Accept': 'application/json' } })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data || !data.id || !data.created_at) return scheduleNext();
                var createdAt = new Date(data.created_at).getTime();
                if (createdAt >= startedAt) {
                    if (!sessionStorage.getItem('pendingAnalysis')) return;
                    sessionStorage.removeItem('pendingAnalysis');
                    _showCompletionBanner(data);
                } else {
                    scheduleNext();
                }
            })
            .catch(function() { scheduleNext(); });
    }

    function scheduleNext() {
        if (!sessionStorage.getItem('pendingAnalysis')) return;
        var now = Date.now();
        var age = now - startedAt;
        if (age > 90000) {
            sessionStorage.removeItem('pendingAnalysis');
            _showErrorBanner('Analisi non completata. Riprova dalla pagina di analisi.');
            return;
        }
        if (age > 300000) {
            sessionStorage.removeItem('pendingAnalysis');
            return;
        }
        setTimeout(poll, 3000);
    }

    poll();
}

function _showErrorBanner(msg) {
    if (document.querySelector('.completion-banner-error')) return;

    var banner = document.createElement('div');
    banner.className = 'completion-banner completion-banner-error';

    var info = document.createElement('div');
    info.className = 'completion-banner-info';
    var strong = document.createElement('strong');
    strong.textContent = msg;
    info.appendChild(strong);
    banner.appendChild(info);

    var link = document.createElement('a');
    link.href = '/analyze';
    link.className = 'btn btn-primary btn-sm no-underline';
    link.textContent = 'Riprova';
    banner.appendChild(link);

    var dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'btn btn-ghost btn-sm completion-dismiss';
    dismiss.textContent = '\u00D7';
    dismiss.onclick = function() { banner.remove(); };
    banner.appendChild(dismiss);

    var content = document.querySelector('.content-inner') || document.querySelector('main') || document.body;
    content.insertBefore(banner, content.firstChild);
}

function _showCompletionBanner(data) {
    if (window.location.pathname === '/analysis/' + data.id) return;
    if (document.querySelector('.completion-banner')) return;

    var banner = document.createElement('div');
    banner.className = 'completion-banner';

    var info = document.createElement('div');
    info.className = 'completion-banner-info';
    var strong = document.createElement('strong');
    strong.textContent = 'Analisi completata!';
    var span = document.createElement('span');
    span.textContent = ' ' + (data.role || '') + ' @ ' + (data.company || '');
    info.appendChild(strong);
    info.appendChild(span);
    banner.appendChild(info);

    var link = document.createElement('a');
    link.href = '/analysis/' + encodeURIComponent(data.id);
    link.className = 'btn btn-primary btn-sm no-underline';
    link.textContent = 'Apri';
    banner.appendChild(link);

    var dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'btn btn-ghost btn-sm completion-dismiss';
    dismiss.textContent = '\u00D7';
    dismiss.onclick = function() { banner.remove(); };
    banner.appendChild(dismiss);

    var content = document.querySelector('.content-inner') || document.querySelector('main') || document.body;
    content.insertBefore(banner, content.firstChild);
}


/**
 * Handle 429 rate limit responses from fetch calls.
 * Returns true if response was a 429 (caller should stop processing).
 */
function handleRateLimit(response, msg) {
    if (response.status === 429) {
        var retryAfter = response.headers.get('Retry-After') || '60';
        if (typeof showToast === 'function') {
            showToast((msg || 'Troppe richieste') + '. Riprova tra ' + retryAfter + ' secondi.', 'error');
        }
        return true;
    }
    return false;
}
