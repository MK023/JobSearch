/**
 * Alpine.js component for the DB cleanup section in /settings.
 * Read-only preview via GET /analysis/cleanup-preview, destructive
 * action via DELETE /analysis/cleanup with explicit confirm.
 */

function cleanupForm() {
    return {
        days: 90,
        maxScore: 40,
        count: null,
        loading: false,
        message: '',

        preview: function() {
            this.loading = true;
            this.message = '';
            var qs = '?days=' + encodeURIComponent(this.days) + '&max_score=' + encodeURIComponent(this.maxScore);
            var self = this;
            fetch('/analysis/cleanup-preview' + qs)
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

        confirmDelete: function() {
            if (this.count === null || this.count <= 0) return;
            var ok = window.confirm(
                'Confermi l\'eliminazione di ' + this.count + ' analisi? L\'operazione non e\' reversibile.'
            );
            if (!ok) return;
            this.loading = true;
            this.message = '';
            var qs = '?days=' + encodeURIComponent(this.days)
                + '&max_score=' + encodeURIComponent(this.maxScore)
                + '&dry_run=false';
            var self = this;
            fetch('/analysis/cleanup' + qs, { method: 'DELETE' })
                .then(function(r) {
                    if (!r.ok) throw new Error('cleanup failed: ' + r.status);
                    return r.json();
                })
                .then(function(data) {
                    self.message = 'Eliminate ' + data.deleted + ' analisi.';
                    self.count = 0;
                })
                .catch(function(e) { self.message = 'Errore: ' + e.message; })
                .finally(function() { self.loading = false; });
        }
    };
}
