/**
 * Alpine.js component for the bulk-reject toolbar on /history.
 * Targets da_valutare analyses older than N days with score <= max_score,
 * transitions them to "scartato" in a single transaction.
 */

function bulkRejectForm() {
    return {
        open: false,
        days: 14,
        maxScore: 60,
        count: null,
        loading: false,
        message: '',

        toggle: function() {
            this.open = !this.open;
            if (this.open && this.count === null) this.preview();
        },

        preview: function() {
            this.loading = true;
            this.message = '';
            const qs = '?days=' + encodeURIComponent(this.days) + '&max_score=' + encodeURIComponent(this.maxScore);
            const self = this;
            fetch('/analysis/bulk-reject-preview' + qs)
                .then(function(r) {
                    if (!r.ok) throw new Error('preview failed: ' + r.status);
                    return r.json();
                })
                .then(function(data) { self.count = data.count; })
                .catch(function(e) {
                    self.count = null;
                    self.message = 'Errore anteprima: ' + e.message;
                })
                .finally(function() { self.loading = false; });
        },

        confirmReject: function() {
            if (this.count === null || this.count <= 0) return;
            const ok = window.confirm(
                'Confermi di scartare ' + this.count + ' analisi? Potrai rimetterle in valutazione una alla volta dalla loro pagina.'
            );
            if (!ok) return;
            this.loading = true;
            this.message = '';
            const qs = '?days=' + encodeURIComponent(this.days) + '&max_score=' + encodeURIComponent(this.maxScore);
            const self = this;
            fetch('/analysis/bulk-reject' + qs, { method: 'POST' })
                .then(function(r) {
                    if (!r.ok) throw new Error('bulk-reject failed: ' + r.status);
                    return r.json();
                })
                .then(function(data) {
                    self.message = 'Scartate ' + data.rejected + ' analisi. Ricarica per vedere i nuovi conteggi.';
                    self.count = 0;
                })
                .catch(function(e) { self.message = 'Errore: ' + e.message; })
                .finally(function() { self.loading = false; });
        }
    };
}
