/**
 * Main Alpine.js root component and application initializer.
 *
 * Module scripts (loaded before this file):
 *   - spending.js   -> initBudgetEditing(), refreshSpending()
 *   - dashboard.js  -> refreshDashboard()
 *   - history.js    -> historyTabs(), refreshHistoryCounts()
 *   - status.js     -> setStatus(), deleteAnalysis()
 *   - batch.js      -> batchManager()
 *   - contacts.js   -> toggleContacts(), loadContacts(), saveContact(), deleteContact()
 *   - followup.js   -> genFollowup(), genLinkedin(), markFollowupDone()
 *   - cv.js         -> uploadCV(), initCVUpload()
 */

function app() {
    return {
        analyzeLoading: false,
        coverLetterLoading: false,

        init: function() {
            // Initialize non-Alpine modules
            initBudgetEditing();
            initCVUpload();

            // Periodic refresh of spending + dashboard (every 30s)
            setInterval(refreshAll, 30000);

            // Refresh on tab focus / visibility change
            document.addEventListener('visibilitychange', function() {
                if (!document.hidden) refreshAll();
            });
            window.addEventListener('focus', refreshAll);
        }
    };
}


/**
 * Refresh both spending and dashboard data.
 */
function refreshAll() {
    refreshSpending();
    refreshDashboard();
}


/**
 * Handle 429 rate limit responses from fetch calls.
 * Returns true if response was a 429 (caller should stop processing).
 */
function handleRateLimit(response, msg) {
    if (response.status === 429) {
        var retryAfter = response.headers.get('Retry-After') || '60';
        alert((msg || 'Troppe richieste') + '. Riprova tra ' + retryAfter + ' secondi.');
        return true;
    }
    return false;
}
