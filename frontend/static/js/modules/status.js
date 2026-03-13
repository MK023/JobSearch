/**
 * Analysis status management and deletion.
 *
 * Status buttons use .status-toggle container + .status-option buttons.
 * After status change, redirects to /analyze for next analysis.
 */

function setStatus(btn) {
    var group = btn.closest('.status-toggle');
    var id = group.dataset.analysisId;
    var status = btn.dataset.status;

    // Intercept colloquio: open modal instead of direct status change
    if (status === 'colloquio') {
        openInterviewModal(id);
        return;
    }

    fetch('/api/v1/status/' + id + '/' + status, {
        method: 'POST',
        headers: { 'Accept': 'application/json' }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            var labels = {da_valutare: 'Da valutare', candidato: 'Candidato', colloquio: 'Colloquio', scartato: 'Scartato'};

            // Update status options
            group.querySelectorAll('.status-option').forEach(function(b) {
                b.classList.remove('active');
            });
            btn.classList.add('active');

            // Update history item if on history page
            var histItem = document.querySelector('[data-hist-id="' + id + '"]');
            if (histItem) {
                histItem.dataset.histStatus = status;
                var stEl = histItem.querySelector('.status-badge');
                if (stEl) {
                    stEl.className = 'status-badge status-' + status;
                    stEl.textContent = labels[status] || status;
                }
            }

            if (typeof refreshHistoryCounts === 'function') refreshHistoryCounts();
            if (typeof refreshSpending === 'function') refreshSpending();
            if (typeof refreshDashboard === 'function') refreshDashboard();

            // Hide cover letter if rejected
            if (status === 'scartato') {
                var clCard = document.getElementById('cover-letter-card');
                var clResult = document.getElementById('cover-letter-result-card');
                if (clCard) clCard.style.display = 'none';
                if (clResult) clResult.style.display = 'none';
            }

            showToast('Stato aggiornato: ' + (labels[status] || status), 'success');
        }
    })
    .catch(function(e) {
        console.error('setStatus error:', e);
        showToast('Errore aggiornamento stato', 'error');
    });
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
            // If on history page, remove the item from DOM
            var histItem = document.querySelector('[data-hist-id="' + id + '"]');
            if (histItem) {
                histItem.remove();
                if (typeof refreshHistoryCounts === 'function') refreshHistoryCounts();
            }

            if (typeof refreshSpending === 'function') refreshSpending();
            if (typeof refreshDashboard === 'function') refreshDashboard();

            showToast('Analisi eliminata', 'success');

            // If on detail page, redirect to analyze
            if (window.location.pathname.indexOf('/analysis/') !== -1) {
                window.location.href = '/analyze';
            }
        }
    })
    .catch(function(e) {
        console.error('deleteAnalysis error:', e);
        showToast('Errore eliminazione analisi', 'error');
    });
}
