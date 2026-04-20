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
            // Fetch current batch state from server — survives reloads and deploys.
            fetch('/api/v1/batch/status')
                .then((r) => r.json())
                .then((data) => {
                    if (!data || data.status === 'empty' || !data.items) return;
                    this.items = data.items.map(function(item) {
                        return {
                            id: item.id,
                            preview: item.preview || '',
                            status: item.status,
                            analysis_id: item.analysis_id,
                            error_message: item.error_message
                        };
                    });
                    this.lastKnownBatchId = data.batch_id;
                    if (data.status === 'running') {
                        this.running = true;
                        this.statusText = 'Analisi in corso...';
                        this.pollStatus();
                    } else if (data.status === 'done' && data.total > 0) {
                        this.statusText = 'Batch completato. Svuota la coda per iniziarne uno nuovo.';
                    }
                })
                .catch((e) => { console.error('batchInit error:', e); });
        },

        addItem: function() {
            const jd = this.batchJd.trim();
            if (!jd) return;

            const url = this.batchUrl.trim();
            const model = this.batchModel;

            const fd = new FormData();
            fd.append('job_description', jd);
            fd.append('job_url', url);
            fd.append('model', model);

            fetch('/api/v1/batch/add', { method: 'POST', body: fd })
                .then(function(r) {
                    if (handleRateLimit(r, 'Troppe richieste batch')) return null;
                    return r.json();
                })
                .then((data) => {
                    if (!data) return;
                    if (data.ok) {
                        // Re-sync from server to get real item IDs and status
                        this.init();
                        this.batchJd = '';
                        this.batchUrl = '';
                    }
                })
                .catch((e) => { console.error('batchAdd error:', e); });
        },

        runAll: function() {
            this.running = true;
            this.statusText = 'Analisi in corso...';

            fetch('/api/v1/batch/run', { method: 'POST' })
                .then((r) => {
                    if (handleRateLimit(r, 'Troppe richieste batch')) { this.running = false; return null; }
                    return r.json();
                })
                .then((data) => {
                    if (!data) return;
                    if (data.ok) {
                        this.pollStatus();
                    }
                })
                .catch((e) => {
                    console.error('batchRun error:', e);
                    this.running = false;
                });
        },

        pollStatus: function() {
            fetch('/api/v1/batch/status')
                .then(function(r) { return r.json(); })
                .then((data) => {
                    if (!data?.items) return;
                    // Rebuild items from server — matches by id so order/additions are safe.
                    this.items = data.items.map(function(item) {
                        return {
                            id: item.id,
                            preview: item.preview || '',
                            status: item.status,
                            analysis_id: item.analysis_id,
                            error_message: item.error_message
                        };
                    });

                    if (data.status === 'running' || data.status === 'pending') {
                        setTimeout(() => { this.pollStatus(); }, 2000);
                    } else if (data.status === 'done') {
                        this.running = false;
                        const ok = (data.counts?.done) || 0;
                        const err = (data.counts?.error) || 0;
                        this.statusText = 'Completato: ' + ok + ' ok, ' + err + ' errori';
                        if (typeof refreshSpending === 'function') refreshSpending();
                        showToast('Batch completato (' + ok + '/' + data.total + ') — apro lo storico', 'success');
                        // Auto-redirect to history tab "da_valutare" so user can triage
                        setTimeout(function() {
                            globalThis.location.href = '/history#valutazione';
                        }, 1500);
                    } else if (data.status === 'error') {
                        this.running = false;
                        this.statusText = 'Batch terminato con errori';
                        showToast('Batch terminato con errori', 'error');
                    }
                })
                .catch((e) => {
                    console.error('pollBatch error:', e);
                    // Keep polling — transient errors shouldn't stop the loop
                    setTimeout(() => { this.pollStatus(); }, 5000);
                });
        },

        clearQueue: function() {
            fetch('/api/v1/batch/clear', { method: 'DELETE' })
                .then(function(r) { return r.json(); })
                .then(() => {
                    this.items = [];
                    this.statusText = '';
                    this.running = false;
                })
                .catch((e) => { console.error('batchClear error:', e); });
        }
    };
}
