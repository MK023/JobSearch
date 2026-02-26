/**
 * Main Alpine.js root component and application initializer.
 *
 * Module scripts are loaded per-page via {% block scripts_extra %}.
 * This file provides the root Alpine component used by base.html:
 *   <body x-data="app()" x-init="init()">
 *
 * Available modules (only present if their <script> tag is on this page):
 *   - spending.js   -> initBudgetEditing(), refreshSpending()
 *   - dashboard.js  -> refreshDashboard()
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

            // Periodic refresh only on dashboard (metrics-row is a grid-3col on dashboard)
            if (document.querySelector('.grid-3col')) {
                setInterval(function() {
                    if (typeof refreshDashboard === 'function') refreshDashboard();
                    if (typeof refreshSpending === 'function') refreshSpending();
                }, 60000);
            }
        }
    };
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
