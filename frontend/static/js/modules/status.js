/**
 * Analysis status management and deletion.
 *
 * Status buttons use .status-toggle container + .status-option buttons.
 * After status change, redirects based on navigation context.
 */

function _getReturnUrl() {
    var ref = document.referrer;
    if (ref && ref.indexOf('/history') !== -1) return '/history';
    if (ref && ref.indexOf('/interviews') !== -1) return '/interviews';
    return '/analyze';
}

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
            var labels = {da_valutare: 'Da valutare', candidato: 'Candidato', colloquio: 'Colloquio', offerta: 'Offerta', scartato: 'Scartato'};

            // Update status options visually
            group.querySelectorAll('.status-option').forEach(function(b) {
                b.classList.remove('active');
            });
            btn.classList.add('active');

            // Hide cover letter if rejected
            if (status === 'scartato') {
                var clCard = document.getElementById('cover-letter-card');
                var clResult = document.getElementById('cover-letter-result-card');
                if (clCard) clCard.style.display = 'none';
                if (clResult) clResult.style.display = 'none';
            }

            showToast('Stato aggiornato: ' + (labels[status] || status), 'success');

            // On detail page, redirect back to context (analyze page)
            if (window.location.pathname.indexOf('/analysis/') !== -1) {
                setTimeout(function() {
                    window.location.href = _getReturnUrl();
                }, 800);
                return;
            }

            // On other pages (history), update in place
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
            showToast('Analisi eliminata', 'success');

            // On detail page, redirect back immediately
            if (window.location.pathname.indexOf('/analysis/') !== -1) {
                window.location.href = _getReturnUrl();
                return;
            }

            // On history page, remove from DOM
            var histItem = document.querySelector('[data-hist-id="' + id + '"]');
            if (histItem) {
                histItem.remove();
                if (typeof refreshHistoryCounts === 'function') refreshHistoryCounts();
            }
            if (typeof refreshSpending === 'function') refreshSpending();
        }
    })
    .catch(function(e) {
        console.error('deleteAnalysis error:', e);
        showToast('Errore eliminazione analisi', 'error');
    });
}
