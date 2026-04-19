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
    const html = document.documentElement;
    const current = html.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
}


/**
 * Check if a background analysis completed while user was on another page.
 * Polls /api/v1/analysis/latest and shows a banner if new analysis found.
 * Shows error banner after 90s if analysis never completes.
 */
function _checkPendingAnalysis() {
    // Guard: prevent duplicate polling loops across Alpine re-inits / page navigations.
    // Alpine's app() init() fires on every page load; without this guard, a 90s
    // polling window with 3s interval can spawn N concurrent loops if the user
    // navigates several pages, flooding /api/v1/analysis/latest.
    if (window._pendingAnalysisActive) return;

    const raw = sessionStorage.getItem('pendingAnalysis');
    if (!raw) return;

    let pending;
    try { pending = JSON.parse(raw); } catch (_) { sessionStorage.removeItem('pendingAnalysis'); return; }

    const startedAt = new Date(pending.startedAt).getTime();
    const elapsed = Date.now() - startedAt;

    if (elapsed > 300000) {
        sessionStorage.removeItem('pendingAnalysis');
        return;
    }

    window._pendingAnalysisActive = true;

    function stop() {
        window._pendingAnalysisActive = false;
    }

    function poll() {
        fetch('/api/v1/analysis/latest', { headers: { 'Accept': 'application/json' } })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data || !data.id || !data.created_at) return scheduleNext();
                const createdAt = new Date(data.created_at).getTime();
                if (createdAt >= startedAt) {
                    if (!sessionStorage.getItem('pendingAnalysis')) { stop(); return; }
                    sessionStorage.removeItem('pendingAnalysis');
                    stop();
                    _showCompletionBanner(data);
                } else {
                    scheduleNext();
                }
            })
            .catch(function() { scheduleNext(); });
    }

    function scheduleNext() {
        if (!sessionStorage.getItem('pendingAnalysis')) { stop(); return; }
        const now = Date.now();
        const age = now - startedAt;
        if (age > 90000) {
            sessionStorage.removeItem('pendingAnalysis');
            stop();
            _showErrorBanner('Analisi non completata. Riprova dalla pagina di analisi.');
            return;
        }
        if (age > 300000) {
            sessionStorage.removeItem('pendingAnalysis');
            stop();
            return;
        }
        setTimeout(poll, 3000);
    }

    poll();
}

function _showErrorBanner(msg) {
    if (document.querySelector('.completion-banner-error')) return;

    const banner = document.createElement('div');
    banner.className = 'completion-banner completion-banner-error';

    const info = document.createElement('div');
    info.className = 'completion-banner-info';
    const strong = document.createElement('strong');
    strong.textContent = msg;
    info.appendChild(strong);
    banner.appendChild(info);

    const link = document.createElement('a');
    link.href = '/analyze';
    link.className = 'btn btn-primary btn-sm no-underline';
    link.textContent = 'Riprova';
    banner.appendChild(link);

    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'btn btn-ghost btn-sm completion-dismiss';
    dismiss.textContent = '\u00D7';
    dismiss.onclick = function() { banner.remove(); };
    banner.appendChild(dismiss);

    const content = document.querySelector('.content-inner') || document.querySelector('main') || document.body;
    content.insertBefore(banner, content.firstChild);
}

function _showCompletionBanner(data) {
    if (window.location.pathname === '/analysis/' + data.id) return;
    if (document.querySelector('.completion-banner')) return;

    const banner = document.createElement('div');
    banner.className = 'completion-banner';

    const info = document.createElement('div');
    info.className = 'completion-banner-info';
    const strong = document.createElement('strong');
    strong.textContent = 'Analisi completata!';
    const span = document.createElement('span');
    span.textContent = ' ' + (data.role || '') + ' @ ' + (data.company || '');
    info.appendChild(strong);
    info.appendChild(span);
    banner.appendChild(info);

    const link = document.createElement('a');
    link.href = '/analysis/' + encodeURIComponent(data.id);
    link.className = 'btn btn-primary btn-sm no-underline';
    link.textContent = 'Apri';
    banner.appendChild(link);

    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'btn btn-ghost btn-sm completion-dismiss';
    dismiss.textContent = '\u00D7';
    dismiss.onclick = function() { banner.remove(); };
    banner.appendChild(dismiss);

    const content = document.querySelector('.content-inner') || document.querySelector('main') || document.body;
    content.insertBefore(banner, content.firstChild);
}


/**
 * Handle 429 rate limit responses from fetch calls.
 * Returns true if response was a 429 (caller should stop processing).
 */
function handleRateLimit(response, msg) {
    if (response.status === 429) {
        const retryAfter = response.headers.get('Retry-After') || '60';
        if (typeof showToast === 'function') {
            showToast((msg || 'Troppe richieste') + '. Riprova tra ' + retryAfter + ' secondi.', 'error');
        }
        return true;
    }
    return false;
}
