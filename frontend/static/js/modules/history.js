/**
 * Alpine.js component: history tabs with DOM-based filtering.
 *
 * Items get their status from data-hist-status attributes, which are
 * updated imperatively by status.js when a user changes status.
 * The Alpine component handles tab switching and re-filtering.
 */

function historyTabs() {
    return {
        activeTab: 'valutazione',

        counts: {
            valutazione: 0,
            applicato: 0,
            skippato: 0
        },

        init: function() {
            this.filterItems();
        },

        switchTab: function(tab) {
            this.activeTab = tab;
            this.filterItems();
        },

        filterItems: function() {
            var tab = this.activeTab;
            var countVal = 0, countApp = 0, countSkip = 0;

            document.querySelectorAll('.history-item[data-hist-status]').forEach(function(item) {
                var st = item.dataset.histStatus || 'da_valutare';
                var isVal = st === 'da_valutare';
                var isApp = st === 'candidato' || st === 'colloquio';
                var isSkip = st === 'scartato';

                // Show/hide based on active tab
                if (tab === 'valutazione') item.style.display = isVal ? '' : 'none';
                else if (tab === 'applicato') item.style.display = isApp ? '' : 'none';
                else item.style.display = isSkip ? '' : 'none';

                // Count
                if (isVal) countVal++;
                if (isApp) countApp++;
                if (isSkip) countSkip++;
            });

            this.counts.valutazione = countVal;
            this.counts.applicato = countApp;
            this.counts.skippato = countSkip;
        }
    };
}


/**
 * Global function to refresh history tab counts and visibility
 * after imperative status changes. Called by status.js.
 */
function refreshHistoryCounts() {
    var histEl = document.querySelector('.history-section');
    if (!histEl) return;

    // Access Alpine v3 data and re-filter
    if (typeof Alpine !== 'undefined') {
        try {
            var data = Alpine.$data(histEl);
            if (data && data.filterItems) {
                data.filterItems();
            }
        } catch (e) {
            // Fallback: just re-query DOM
            console.warn('Could not access Alpine data for history, falling back', e);
        }
    }
}
