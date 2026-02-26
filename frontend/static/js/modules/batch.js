/**
 * Alpine.js component: batch analysis queue management.
 */

function batchManager() {
    return {
        items: [],
        batchUrl: '',
        batchJd: '',
        batchModel: 'haiku',
        running: false,
        statusText: '',

        statusColor: function(status) {
            if (status === 'done') return '#34d399';
            if (status === 'running') return '#fbbf24';
            if (status === 'error') return '#f87171';
            return '#64748b';
        },

        addItem: function() {
            var jd = this.batchJd.trim();
            if (!jd) return;

            var url = this.batchUrl.trim();
            var model = this.batchModel;
            var self = this;

            var fd = new FormData();
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
                        self.items.push({
                            preview: jd.substring(0, 80) + (jd.length > 80 ? '...' : ''),
                            status: 'pending',
                            result_preview: ''
                        });
                        self.batchJd = '';
                        self.batchUrl = '';
                    }
                })
                .catch(function(e) { console.error('batchAdd error:', e); });
        },

        runAll: function() {
            var self = this;
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
            var self = this;

            fetch('/api/v1/batch/status')
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.items) {
                        data.items.forEach(function(item, i) {
                            if (self.items[i]) {
                                self.items[i].status = item.status;
                                if (item.result_preview) {
                                    self.items[i].result_preview = item.result_preview;
                                }
                            }
                        });
                    }
                    if (data.status === 'running') {
                        setTimeout(function() { self.pollStatus(); }, 2000);
                    } else if (data.status === 'done') {
                        self.running = false;
                        self.statusText = 'Completato! Ricarica la pagina per vedere i risultati.';
                        if (typeof refreshSpending === 'function') refreshSpending();
                        if (typeof refreshDashboard === 'function') refreshDashboard();
                        showToast('Analisi batch completata', 'success');
                    }
                })
                .catch(function(e) { console.error('pollBatch error:', e); });
        },

        clearQueue: function() {
            var self = this;

            fetch('/api/v1/batch/clear', { method: 'DELETE' })
                .then(function(r) { return r.json(); })
                .then(function() {
                    self.items = [];
                    self.statusText = '';
                })
                .catch(function(e) { console.error('batchClear error:', e); });
        }
    };
}
