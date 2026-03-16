/**
 * AJAX analysis submission with background completion tracking.
 * If user navigates away during analysis, a banner appears when done.
 */

function submitAnalysis(e) {
    e.preventDefault();

    var form = e.target;
    var jobDesc = form.querySelector('#job_description').value;
    var jobUrl = form.querySelector('#job_url').value;
    var modelEl = form.querySelector('input[name="model"]:checked');
    var model = modelEl ? modelEl.value : 'haiku';

    if (!jobDesc.trim()) {
        showToast('Inserisci la descrizione del lavoro', 'error');
        return false;
    }

    // Update Alpine loading state
    var wrapper = form.closest('[x-data]');
    if (wrapper && typeof Alpine !== 'undefined') {
        try { Alpine.$data(wrapper).analyzeLoading = true; } catch (_) {}
    }

    // Track pending analysis for cross-page notification
    sessionStorage.setItem('pendingAnalysis', JSON.stringify({
        startedAt: new Date().toISOString()
    }));

    var payload = JSON.stringify({
        job_description: jobDesc,
        job_url: jobUrl,
        model: model
    });

    fetch('/api/v1/analyze', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: payload,
        keepalive: true
    })
    .then(function(r) {
        if (r.status === 429) {
            showToast('Troppe richieste, riprova tra poco', 'error');
            resetLoading(wrapper);
            sessionStorage.removeItem('pendingAnalysis');
            return null;
        }
        return r.json();
    })
    .then(function(data) {
        if (!data) return;
        sessionStorage.removeItem('pendingAnalysis');
        if (data.error) {
            _showAnalysisError(data.error);
            resetLoading(wrapper);
        } else if (data.redirect) {
            window.location.href = data.redirect;
        }
    })
    .catch(function(err) {
        if (err && err.name === 'AbortError') return;
        if (document.visibilityState === 'hidden') return;
        setTimeout(function() {
            if (document.visibilityState === 'hidden') return;
            showToast('Errore di rete', 'error');
            resetLoading(wrapper);
            sessionStorage.removeItem('pendingAnalysis');
        }, 200);
    });

    return false;
}

function resetLoading(wrapper) {
    if (wrapper && typeof Alpine !== 'undefined') {
        try { Alpine.$data(wrapper).analyzeLoading = false; } catch (_) {}
    }
}

function _showAnalysisError(msg) {
    var existing = document.querySelector('.analysis-error-banner');
    if (existing) existing.remove();

    var banner = document.createElement('div');
    banner.className = 'message-banner banner-error analysis-error-banner';

    var text = document.createElement('span');
    text.textContent = msg;
    banner.appendChild(text);

    var dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'btn btn-ghost btn-sm';
    dismiss.textContent = '\u00D7';
    dismiss.style.marginLeft = 'auto';
    dismiss.onclick = function() { banner.remove(); };
    banner.appendChild(dismiss);

    var target = document.querySelector('.content-inner');
    var header = target ? target.querySelector('.page-header') : null;
    if (header && header.nextSibling) {
        target.insertBefore(banner, header.nextSibling);
    } else if (target) {
        target.insertBefore(banner, target.firstChild);
    }

    if (typeof showToast === 'function') showToast(msg, 'error');
}
