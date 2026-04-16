/**
 * Alpine.js component: history tabs + secondary filters with DOM-based filtering.
 *
 * Items get their status from data-hist-status attributes, which are
 * updated imperatively by status.js when a user changes status.
 * The Alpine component handles tab switching, contract type (dipendente vs
 * P.IVA vs tutti), secondary filters (hide body_rental / recruiter, min score)
 * and re-filtering.
 *
 * Tab counts always reflect the TOTAL per status (independent of secondary
 * filters) so the user does not see "0" when items are just filtered out.
 *
 * "colloquio" status items are grouped under "candidature" since
 * interviews have their own dedicated page.
 */

function historyTabs() {
    var validTabs = ['valutazione', 'candidature', 'scartati', 'rifiutati'];
    var validContractTypes = ['tutti', 'dipendente', 'piva'];
    var FILTERS_KEY = 'historyFilters';
    var defaultFilters = {
        contractType: 'tutti',
        hideBodyRental: false,
        hideRecruiter: false,
        minScore: 0,
        searchQuery: ''
    };

    function loadFilters() {
        try {
            var raw = sessionStorage.getItem(FILTERS_KEY);
            if (!raw) return Object.assign({}, defaultFilters);
            var parsed = JSON.parse(raw);
            // Legacy migration: old `hideFreelance: true` -> `contractType: 'dipendente'`
            var contractType = parsed.contractType;
            if (!contractType && parsed.hideFreelance) contractType = 'dipendente';
            if (validContractTypes.indexOf(contractType) === -1) contractType = 'tutti';
            return {
                contractType: contractType,
                hideBodyRental: !!parsed.hideBodyRental,
                hideRecruiter: !!parsed.hideRecruiter,
                minScore: Math.max(0, Math.min(100, parseInt(parsed.minScore, 10) || 0)),
                searchQuery: typeof parsed.searchQuery === 'string' ? parsed.searchQuery : ''
            };
        } catch (e) {
            return Object.assign({}, defaultFilters);
        }
    }

    return {
        activeTab: 'valutazione',

        counts: {
            valutazione: 0,
            candidature: 0,
            scartati: 0,
            rifiutati: 0
        },

        filters: Object.assign({}, defaultFilters),

        init: function() {
            // Restore tab from URL hash or sessionStorage
            var hash = location.hash.replace('#', '');
            var stored = sessionStorage.getItem('historyTab');
            var restored = validTabs.indexOf(hash) !== -1 ? hash : (validTabs.indexOf(stored) !== -1 ? stored : 'valutazione');
            this.activeTab = restored;
            this.filters = loadFilters();
            this.filterItems();
        },

        switchTab: function(tab) {
            this.activeTab = tab;
            history.replaceState(null, '', '#' + tab);
            sessionStorage.setItem('historyTab', tab);
            this.filterItems();
        },

        setContractType: function(type) {
            if (validContractTypes.indexOf(type) === -1) return;
            this.filters.contractType = type;
            this.persistFilters();
            this.filterItems();
        },

        toggleFilter: function(name) {
            this.filters[name] = !this.filters[name];
            this.persistFilters();
            this.filterItems();
        },

        setMinScore: function(val) {
            this.filters.minScore = Math.max(0, Math.min(100, parseInt(val, 10) || 0));
            this.persistFilters();
            this.filterItems();
        },

        setSearch: function(query) {
            this.filters.searchQuery = (query || '').toString().trim().toLowerCase();
            this.persistFilters();
            this.filterItems();
        },

        resetFilters: function() {
            this.filters = Object.assign({}, defaultFilters);
            this.persistFilters();
            this.filterItems();
        },

        persistFilters: function() {
            try {
                sessionStorage.setItem(FILTERS_KEY, JSON.stringify(this.filters));
            } catch (e) {
                // sessionStorage full or disabled — silently ignore
            }
        },

        filterItems: function() {
            var tab = this.activeTab;
            var f = this.filters;
            var cVal = 0, cCand = 0, cScar = 0, cRif = 0;

            document.querySelectorAll('.history-item[data-hist-status]').forEach(function(item) {
                var st = item.dataset.histStatus || 'da_valutare';

                var bucket;
                if (st === 'da_valutare') { cVal++; bucket = 'valutazione'; }
                else if (st === 'candidato' || st === 'colloquio' || st === 'offerta') { cCand++; bucket = 'candidature'; }
                else if (st === 'rifiutato') { cRif++; bucket = 'rifiutati'; }
                else { cScar++; bucket = 'scartati'; }

                var matchTab = (tab === bucket);
                var matchFilters = true;
                // Contract type: dipendente -> is_freelance != '1'; piva -> is_freelance === '1'; tutti -> nessun filtro
                var isFreelance = item.dataset.histFreelance === '1';
                if (f.contractType === 'dipendente' && isFreelance) matchFilters = false;
                if (f.contractType === 'piva' && !isFreelance) matchFilters = false;
                if (f.hideBodyRental && item.dataset.histBodyrental === '1') matchFilters = false;
                if (f.hideRecruiter && item.dataset.histRecruiter === '1') matchFilters = false;
                if (f.minScore > 0) {
                    var score = parseInt(item.dataset.histScore, 10) || 0;
                    if (score < f.minScore) matchFilters = false;
                }
                if (f.searchQuery) {
                    var haystack = item.dataset.histSearch || '';
                    if (haystack.indexOf(f.searchQuery) === -1) matchFilters = false;
                }

                item.style.display = (matchTab && matchFilters) ? '' : 'none';
            });

            this.counts.valutazione = cVal;
            this.counts.candidature = cCand;
            this.counts.scartati = cScar;
            this.counts.rifiutati = cRif;
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
