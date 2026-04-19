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
            const qs = '?days=' + encodeURIComponent(this.days) + '&max_score=' + encodeURIComponent(this.maxScore);
            fetch('/analysis/cleanup-preview' + qs)
                .then(function(r) {
                    if (!r.ok) throw new Error('preview failed: ' + r.status);
                    return r.json();
                })
                .then((data) => { this.count = data.count; })
                .catch((e) => {
                    this.count = null;
                    this.message = 'Errore anteprima: ' + e.message;
                })
                .finally(() => { this.loading = false; });
        },

        confirmDelete: function() {
            if (this.count === null || this.count <= 0) return;
            const ok = globalThis.confirm(
                'Confermi l\'eliminazione di ' + this.count + ' analisi? L\'operazione non e\' reversibile.'
            );
            if (!ok) return;
            this.loading = true;
            this.message = '';
            const qs = '?days=' + encodeURIComponent(this.days)
                + '&max_score=' + encodeURIComponent(this.maxScore)
                + '&dry_run=false';
            fetch('/analysis/cleanup' + qs, { method: 'DELETE' })
                .then(function(r) {
                    if (!r.ok) throw new Error('cleanup failed: ' + r.status);
                    return r.json();
                })
                .then((data) => {
                    this.message = 'Eliminate ' + data.deleted + ' analisi.';
                    this.count = 0;
                })
                .catch((e) => { this.message = 'Errore: ' + e.message; })
                .finally(() => { this.loading = false; });
        }
    };
}
