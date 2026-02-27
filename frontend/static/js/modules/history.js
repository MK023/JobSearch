/**
 * Alpine.js component: history tabs with DOM-based filtering.
 *
 * Items get their status from data-hist-status attributes, which are
 * updated imperatively by status.js when a user changes status.
 * The Alpine component handles tab switching and re-filtering.
 *
 * "colloquio" status items are grouped under "candidature" since
 * interviews have their own dedicated page.
 */

function historyTabs() {
    var validTabs = ['valutazione', 'candidature', 'scartati'];

    return {
        activeTab: 'valutazione',

        counts: {
            valutazione: 0,
            candidature: 0,
            scartati: 0
        },

        init: function() {
            // Restore tab from URL hash or sessionStorage
            var hash = location.hash.replace('#', '');
            var stored = sessionStorage.getItem('historyTab');
            var restored = validTabs.indexOf(hash) !== -1 ? hash : (validTabs.indexOf(stored) !== -1 ? stored : 'valutazione');
            this.activeTab = restored;
            this.filterItems();
        },

        switchTab: function(tab) {
            this.activeTab = tab;
            history.replaceState(null, '', '#' + tab);
            sessionStorage.setItem('historyTab', tab);
            this.filterItems();
        },

        filterItems: function() {
            var tab = this.activeTab;
            var cVal = 0, cCand = 0, cScar = 0;

            document.querySelectorAll('.history-item[data-hist-status]').forEach(function(item) {
                var st = item.dataset.histStatus || 'da_valutare';

                var bucket;
                if (st === 'da_valutare') { cVal++; bucket = 'valutazione'; }
                else if (st === 'candidato' || st === 'colloquio') { cCand++; bucket = 'candidature'; }
                else { cScar++; bucket = 'scartati'; }

                item.style.display = (tab === bucket) ? '' : 'none';
            });

            this.counts.valutazione = cVal;
            this.counts.candidature = cCand;
            this.counts.scartati = cScar;
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
