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
    const validTabs = new Set(['valutazione', 'candidature', 'scartati', 'rifiutati']);
    const validContractTypes = new Set(['tutti', 'dipendente', 'piva']);
    const FILTERS_KEY = 'historyFilters';
    const defaultFilters = {
        contractType: 'tutti',
        hideBodyRental: false,
        hideRecruiter: false,
        minScore: 0,
        searchQuery: ''
    };

    function _normalizeContractType(parsed) {
        let contractType = parsed.contractType;
        // Legacy migration: old `hideFreelance: true` -> `contractType: 'dipendente'`
        if (!contractType && parsed.hideFreelance) contractType = 'dipendente';
        return validContractTypes.has(contractType) ? contractType : 'tutti';
    }

    function loadFilters() {
        try {
            const raw = sessionStorage.getItem(FILTERS_KEY);
            if (!raw) return { ...defaultFilters };
            const parsed = JSON.parse(raw);
            return {
                contractType: _normalizeContractType(parsed),
                hideBodyRental: !!parsed.hideBodyRental,
                hideRecruiter: !!parsed.hideRecruiter,
                minScore: Math.max(0, Math.min(100, Number.parseInt(parsed.minScore, 10) || 0)),
                searchQuery: typeof parsed.searchQuery === 'string' ? parsed.searchQuery : ''
            };
        } catch (e) {
            console.debug('historyFilters parse failed, falling back to defaults:', e);
            return { ...defaultFilters };
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

        filters: { ...defaultFilters },

        init: function() {
            // Restore tab from URL hash or sessionStorage (in that priority order)
            const hash = location.hash.replace('#', '');
            if (validTabs.has(hash)) {
                this.activeTab = hash;
            } else {
                const stored = sessionStorage.getItem('historyTab');
                this.activeTab = validTabs.has(stored) ? stored : 'valutazione';
            }
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
            if (!validContractTypes.has(type)) return;
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
            this.filters.minScore = Math.max(0, Math.min(100, Number.parseInt(val, 10) || 0));
            this.persistFilters();
            this.filterItems();
        },

        setSearch: function(query) {
            this.filters.searchQuery = (query || '').toString().trim().toLowerCase();
            this.persistFilters();
            this.filterItems();
        },

        resetFilters: function() {
            this.filters = { ...defaultFilters };
            this.persistFilters();
            this.filterItems();
        },

        persistFilters: function() {
            try {
                sessionStorage.setItem(FILTERS_KEY, JSON.stringify(this.filters));
            } catch (e) {
                // sessionStorage full or disabled — silent fallthrough is intentional,
                // filters live in memory for the session and are restored next reload.
                console.debug('persistFilters failed (quota/private mode):', e);
            }
        },

        _bucketFor: function(status) {
            if (status === 'da_valutare') return 'valutazione';
            if (status === 'candidato' || status === 'colloquio' || status === 'offerta') return 'candidature';
            if (status === 'rifiutato') return 'rifiutati';
            return 'scartati';
        },

        _matchesSecondaryFilters: function(item, f) {
            const isFreelance = item.dataset.histFreelance === '1';
            if (f.contractType === 'dipendente' && isFreelance) return false;
            if (f.contractType === 'piva' && !isFreelance) return false;
            if (f.hideBodyRental && item.dataset.histBodyrental === '1') return false;
            if (f.hideRecruiter && item.dataset.histRecruiter === '1') return false;
            if (f.minScore > 0) {
                const score = Number.parseInt(item.dataset.histScore, 10) || 0;
                if (score < f.minScore) return false;
            }
            if (f.searchQuery) {
                const haystack = item.dataset.histSearch || '';
                if (!haystack.includes(f.searchQuery)) return false;
            }
            return true;
        },

        filterItems: function() {
            const tab = this.activeTab;
            const f = this.filters;
            const counts = { valutazione: 0, candidature: 0, scartati: 0, rifiutati: 0 };
            const self = this;

            document.querySelectorAll('.history-item[data-hist-status]').forEach(function(item) {
                const status = item.dataset.histStatus || 'da_valutare';
                const bucket = self._bucketFor(status);
                counts[bucket] += 1;

                const matchTab = tab === bucket;
                const matchFilters = self._matchesSecondaryFilters(item, f);
                item.style.display = (matchTab && matchFilters) ? '' : 'none';
            });

            this.counts.valutazione = counts.valutazione;
            this.counts.candidature = counts.candidature;
            this.counts.scartati = counts.scartati;
            this.counts.rifiutati = counts.rifiutati;
        }
    };
}


/**
 * Global function to refresh history tab counts and visibility
 * after imperative status changes. Called by status.js.
 */
function refreshHistoryCounts() {
    const histEl = document.querySelector('.history-section');
    if (!histEl) return;

    // Access Alpine v3 data and re-filter
    if (typeof Alpine !== 'undefined') {
        try {
            const data = Alpine.$data(histEl);
            if (data?.filterItems) {
                data.filterItems();
            }
        } catch (e) {
            // Fallback: just re-query DOM
            console.warn('Could not access Alpine data for history, falling back', e);
        }
    }
}
