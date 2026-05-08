/**
 * Analysis status management and deletion.
 *
 * Status buttons use .status-toggle container + .status-option buttons.
 * After status change, redirects based on navigation context.
 */

function _getReturnUrl() {
    const ref = document.referrer;
    if (ref?.includes('/history')) return '/history';
    if (ref?.includes('/interviews')) return '/interviews';
    return '/analyze';
}

const _STATUS_LABELS = {
    da_valutare: 'Da valutare',
    candidato: 'Candidato',
    colloquio: 'Colloquio',
    offerta: 'Offerta',
    scartato: 'Scartato'
};

function _updateStatusToggleUI(group, btn) {
    group.querySelectorAll('.status-option').forEach(function(b) {
        b.classList.remove('active');
    });
    btn.classList.add('active');
}

function _hideCoverLetterCards() {
    const clCard = document.getElementById('cover-letter-card');
    const clResult = document.getElementById('cover-letter-result-card');
    if (clCard) clCard.style.display = 'none';
    if (clResult) clResult.style.display = 'none';
}

function _applyStatusToHistoryRow(id, status) {
    const histItem = document.querySelector('[data-hist-id="' + id + '"]');
    if (!histItem) return;
    histItem.dataset.histStatus = status;
    const stEl = histItem.querySelector('.status-badge');
    if (stEl) {
        stEl.className = 'status-badge status-' + status;
        stEl.textContent = _STATUS_LABELS[status] || status;
    }
}

function _redirectAfterStatusChange() {
    setTimeout(function() {
        globalThis.location.href = _getReturnUrl();
    }, 800);
}

function _handleStatusResponse(group, btn, id, status) {
    _updateStatusToggleUI(group, btn);
    if (status === 'scartato') _hideCoverLetterCards();
    showToast('Stato aggiornato: ' + (_STATUS_LABELS[status] || status), 'success');

    if (globalThis.location.pathname.includes('/analysis/')) {
        _redirectAfterStatusChange();
        return;
    }
    _applyStatusToHistoryRow(id, status);
    if (typeof refreshHistoryCounts === 'function') refreshHistoryCounts();
    if (typeof refreshSpending === 'function') refreshSpending();
}

function setStatus(btn) {
    const group = btn.closest('.status-toggle');
    const id = group.dataset.analysisId;
    const status = btn.dataset.status;

    // Intercept colloquio: open modal instead of direct status change
    if (status === 'colloquio') {
        openInterviewModal(id);
        return;
    }

    fetchJSON('/api/v1/status/' + id + '/' + status, {
        method: 'POST',
        headers: { 'Accept': 'application/json' }
    })
    .then(function(data) {
        if (data.ok) _handleStatusResponse(group, btn, id, status);
    })
    .catch(function(e) {
        console.error('setStatus error:', e);
        showToast('Errore aggiornamento stato', 'error');
    });
}


function deleteAnalysis(id) {
    if (!confirm('Sei sicuro di voler eliminare questa analisi? Verra\' rimossa anche ogni cover letter associata.')) return;

    fetchJSON('/api/v1/analysis/' + id, {
        method: 'DELETE',
        headers: { 'Accept': 'application/json' }
    })
    .then(function(data) {
        if (data.ok) {
            showToast('Analisi eliminata', 'success');

            // On detail page, redirect back immediately
            if (globalThis.location.pathname.includes('/analysis/')) {
                globalThis.location.href = _getReturnUrl();
                return;
            }

            // On history page, remove from DOM
            const histItem = document.querySelector('[data-hist-id="' + id + '"]');
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
