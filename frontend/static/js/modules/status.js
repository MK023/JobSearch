/**
 * Analysis status management, action cards, and deletion.
 *
 * Mouse clicks on macOS can fail due to elastic overscroll shifting the page
 * between mousedown and mouseup, preventing the browser from generating a
 * click event.  We work around this with a capture-phase pointerdown listener
 * that fires only for mouse pointers (pointerType === "mouse").  Touch and
 * pen interactions are left to the normal click path, which works reliably on
 * mobile and tablet devices.
 */

var _busy = {};

function guardAction(key, fn) {
    if (_busy[key]) return;
    _busy[key] = true;
    try { fn(); } finally {
        setTimeout(function() { delete _busy[key]; }, 800);
    }
}

// Action card dispatcher
var ACTION_HANDLERS = {
    interview: function(id) { openInterviewModal(id); },
    followup:  function(id) { genFollowup(id); },
    linkedin:  function(id) { genLinkedin(id); },
    contacts:  function(id) { toggleContacts(id); }
};

function dispatchActionCard(card) {
    var action = card.dataset.action;
    var id = card.dataset.id;
    if (!action || !id) return;
    var handler = ACTION_HANDLERS[action];
    if (handler) handler(id);
}


// Mouse-only pointerdown in capture phase — fixes macOS elastic bounce
document.addEventListener('pointerdown', function(e) {
    if (e.pointerType !== 'mouse') return;

    var statusBtn = e.target.closest('.status-option');
    if (statusBtn) {
        e.preventDefault();
        guardAction('status-' + statusBtn.dataset.status, function() {
            setStatus(statusBtn);
        });
        return;
    }

    var actionCard = e.target.closest('.action-card[data-action]');
    if (actionCard) {
        e.preventDefault();
        guardAction('action-' + actionCard.dataset.action, function() {
            dispatchActionCard(actionCard);
        });
        return;
    }

    var deleteBtn = e.target.closest('[data-action-delete]');
    if (deleteBtn) {
        e.preventDefault();
        guardAction('delete', function() {
            deleteAnalysis(deleteBtn.getAttribute('data-action-delete'));
        });
        return;
    }
}, true);


// Touch/pen: normal click delegation (pointerdown skips non-mouse)
document.addEventListener('click', function(e) {
    var actionCard = e.target.closest('.action-card[data-action]');
    if (actionCard) {
        guardAction('action-' + actionCard.dataset.action, function() {
            dispatchActionCard(actionCard);
        });
    }
});


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

            // On detail page, redirect to new analysis after brief delay
            if (window.location.pathname.indexOf('/analysis/') !== -1) {
                setTimeout(function() {
                    window.location.href = '/analyze';
                }, 1200);
            }
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
