/**
 * Alpine.js component: batch analysis queue management.
 *
 * State model: DB is source of truth. On mount, init() fetches /batch/status
 * and repopulates items. If a batch is running, polling auto-resumes. If the
 * batch just finished (status=done) but the user hasn't acknowledged it yet,
 * we show a success toast and optional reload prompt.
 */

function batchManager() {
    return {
        items: [],
        batchUrl: '',
        batchJd: '',
        batchModel: 'haiku',
        running: false,
        statusText: '',
        lastKnownBatchId: null,

        statusColor: function(status) {
            if (status === 'done') return '#34d399';
            if (status === 'running') return '#fbbf24';
            if (status === 'error') return '#f87171';
            if (status === 'skipped') return '#94a3b8';
            return '#64748b';
        },

        init: function() {
            const self = this;
            // Fetch current batch state from server — survives reloads and deploys.
            fetch('/api/v1/batch/status')
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (!data || data.status === 'empty' || !data.items) return;
                    self.items = data.items.map(function(item) {
                        return {
                            id: item.id,
                            preview: item.preview || '',
                            status: item.status,
                            analysis_id: item.analysis_id,
                            error_message: item.error_message
                        };
                    });
                    self.lastKnownBatchId = data.batch_id;
                    if (data.status === 'running') {
                        self.running = true;
                        self.statusText = 'Analisi in corso...';
                        self.pollStatus();
                    } else if (data.status === 'done' && data.total > 0) {
                        self.statusText = 'Batch completato. Svuota la coda per iniziarne uno nuovo.';
                    }
                })
                .catch(function(e) { console.error('batchInit error:', e); });
        },

        addItem: function() {
            const jd = this.batchJd.trim();
            if (!jd) return;

            const url = this.batchUrl.trim();
            const model = this.batchModel;
            const self = this;

            const fd = new FormData();
            fd.append('job_description', jd);
            fd.append('job_url', url);
            fd.append('model', model);

            fetch('/api/v1/batch/add', { method: 'POST', body: fd })
                .then(function(r) {
                    if (handleRateLimit(r, 'Troppe richieste batch')) return null;
                    return r.json();
                })
                .then(function(data) {
                    if (!data) return;
                    if (data.ok) {
                        // Re-sync from server to get real item IDs and status
                        self.init();
                        self.batchJd = '';
                        self.batchUrl = '';
                    }
                })
                .catch(function(e) { console.error('batchAdd error:', e); });
        },

        runAll: function() {
            const self = this;
            self.running = true;
            self.statusText = 'Analisi in corso...';

            fetch('/api/v1/batch/run', { method: 'POST' })
                .then(function(r) {
                    if (handleRateLimit(r, 'Troppe richieste batch')) { self.running = false; return null; }
                    return r.json();
                })
                .then(function(data) {
                    if (!data) return;
                    if (data.ok) {
                        self.pollStatus();
                    }
                })
                .catch(function(e) {
                    console.error('batchRun error:', e);
                    self.running = false;
                });
        },

        pollStatus: function() {
            const self = this;

            fetch('/api/v1/batch/status')
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (!data || !data.items) return;
                    // Rebuild items from server — matches by id so order/additions are safe.
                    self.items = data.items.map(function(item) {
                        return {
                            id: item.id,
                            preview: item.preview || '',
                            status: item.status,
                            analysis_id: item.analysis_id,
                            error_message: item.error_message
                        };
                    });

                    if (data.status === 'running' || data.status === 'pending') {
                        setTimeout(function() { self.pollStatus(); }, 2000);
                    } else if (data.status === 'done') {
                        self.running = false;
                        const ok = data.counts && data.counts.done || 0;
                        const err = data.counts && data.counts.error || 0;
                        self.statusText = 'Completato: ' + ok + ' ok, ' + err + ' errori';
                        if (typeof refreshSpending === 'function') refreshSpending();
                        showToast('Batch completato (' + ok + '/' + data.total + ') — apro lo storico', 'success');
                        // Auto-redirect to history tab "da_valutare" so user can triage
                        setTimeout(function() {
                            window.location.href = '/history#valutazione';
                        }, 1500);
                    } else if (data.status === 'error') {
                        self.running = false;
                        self.statusText = 'Batch terminato con errori';
                        showToast('Batch terminato con errori', 'error');
                    }
                })
                .catch(function(e) {
                    console.error('pollBatch error:', e);
                    // Keep polling — transient errors shouldn't stop the loop
                    setTimeout(function() { self.pollStatus(); }, 5000);
                });
        },

        clearQueue: function() {
            const self = this;

            fetch('/api/v1/batch/clear', { method: 'DELETE' })
                .then(function(r) { return r.json(); })
                .then(function() {
                    self.items = [];
                    self.statusText = '';
                    self.running = false;
                })
                .catch(function(e) { console.error('batchClear error:', e); });
        }
    };
}
