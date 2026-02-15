/**
 * Analysis status management and deletion.
 */

function setStatus(btn) {
    var group = btn.closest('.pill-group');
    var id = group.dataset.analysisId;
    var status = btn.dataset.status;

    fetch('/api/v1/status/' + id + '/' + status, {
        method: 'POST',
        headers: { 'Accept': 'application/json' }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            // Update pill buttons
            group.querySelectorAll('.pill-btn').forEach(function(b) {
                b.classList.remove('active');
            });
            btn.classList.add('active');

            // Update history item
            var histItem = document.querySelector('[data-hist-id="' + id + '"]');
            if (histItem) {
                histItem.dataset.histStatus = status;
                var stEl = histItem.querySelector('.status-badge');
                if (stEl) {
                    stEl.className = 'status-badge status-badge-' + status;
                    var icons = {
                        'da_valutare': '\uD83D\uDD0D',
                        'candidato': '\uD83D\uDCE8',
                        'colloquio': '\uD83D\uDDE3\uFE0F',
                        'scartato': '\u274C'
                    };
                    stEl.textContent = (icons[status] || '') + ' ' + status.replace('_', ' ');
                }
            }

            refreshHistoryCounts();
            refreshSpending();
            refreshDashboard();

            // Hide cover letter if rejected
            var clCard = document.getElementById('cover-letter-card');
            var clResult = document.getElementById('cover-letter-result-card');
            if (status === 'scartato') {
                if (clCard) clCard.style.display = 'none';
                if (clResult) clResult.style.display = 'none';
            }

            // Remove result card only when rejected
            if (status === 'scartato') {
                var resCard = btn.closest('.result-card');
                if (resCard) resCard.remove();
            }
        }
    })
    .catch(function(e) { console.error('setStatus error:', e); });
}


function deleteAnalysis(id) {
    if (!confirm('Sei sicuro di voler eliminare questa analisi? Verra\' rimossa anche ogni cover letter associata.')) return;

    fetch('/api/v1/analysis/' + id, {
        method: 'DELETE',
        headers: { 'Accept': 'application/json' }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            // Remove from history
            var histItem = document.querySelector('[data-hist-id="' + id + '"]');
            if (histItem) histItem.remove();

            // Remove result card
            var actionsEl = document.getElementById('actions-' + id);
            if (actionsEl) {
                var resCard = actionsEl.closest('.result-card');
                if (resCard) resCard.remove();
            }

            // Hide cover letter if it was for this analysis
            var clIdEl = document.getElementById('cover-letter-analysis-id');
            if (clIdEl && clIdEl.value === id) {
                var clCard = document.getElementById('cover-letter-card');
                if (clCard) clCard.style.display = 'none';
                var clResult = document.getElementById('cover-letter-result-card');
                if (clResult) clResult.style.display = 'none';
            }

            refreshHistoryCounts();
            refreshSpending();
            refreshDashboard();
        }
    })
    .catch(function(e) { console.error('deleteAnalysis error:', e); });
}
