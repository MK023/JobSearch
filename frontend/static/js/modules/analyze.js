/**
 * AJAX analysis submission with background completion tracking.
 * If user navigates away during analysis, a banner appears when done.
 */

function submitAnalysis(e) {
    e.preventDefault();

    const form = e.target;
    const jobDesc = form.querySelector('#job_description').value;
    const jobUrl = form.querySelector('#job_url').value;
    const modelEl = form.querySelector('input[name="model"]:checked');
    const model = modelEl ? modelEl.value : 'haiku';

    if (!jobDesc.trim()) {
        showToast('Inserisci la descrizione del lavoro', 'error');
        return false;
    }

    // Update Alpine loading state
    const wrapper = form.closest('[x-data]');
    if (wrapper && typeof Alpine !== 'undefined') {
        try { Alpine.$data(wrapper).analyzeLoading = true; } catch (e) {
            // Alpine wrapper not yet initialised — loading indicator is nice-to-have.
            console.debug('Alpine.$data write failed:', e);
        }
    }

    // Track pending analysis for cross-page notification
    sessionStorage.setItem('pendingAnalysis', JSON.stringify({
        startedAt: new Date().toISOString()
    }));

    const payload = JSON.stringify({
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
        if (!r.ok) {
            // 5xx/4xx (≠429): server in errore → toast + reset loading
            // invece di crashare su r.json() che parserebbe HTML d'errore.
            throw new Error('analyze HTTP ' + r.status);
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
            globalThis.location.href = data.redirect;
        }
    })
    .catch(function(err) {
        if (err?.name === 'AbortError') return;
        if (document.visibilityState === 'hidden') return;
        sessionStorage.removeItem('pendingAnalysis');
        const msg = (err?.message || '').includes('HTTP 5')
            ? 'Errore server, riprova tra poco'
            : 'Errore di rete';
        setTimeout(function() {
            if (document.visibilityState === 'hidden') return;
            showToast(msg, 'error');
            resetLoading(wrapper);
        }, 200);
    });

    return false;
}

function resetLoading(wrapper) {
    if (wrapper && typeof Alpine !== 'undefined') {
        try { Alpine.$data(wrapper).analyzeLoading = false; } catch (e) {
            // Alpine wrapper not yet initialised — loading indicator is nice-to-have.
            console.debug('Alpine.$data write failed:', e);
        }
    }
}

function _showAnalysisError(msg) {
    const existing = document.querySelector('.analysis-error-banner');
    if (existing) existing.remove();

    const banner = document.createElement('div');
    banner.className = 'message-banner banner-error analysis-error-banner';

    const text = document.createElement('span');
    text.textContent = msg;
    banner.appendChild(text);

    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'btn btn-ghost btn-sm';
    dismiss.textContent = '\u00D7';
    dismiss.style.marginLeft = 'auto';
    dismiss.onclick = function() { banner.remove(); };
    banner.appendChild(dismiss);

    const target = document.querySelector('.content-inner');
    const header = target ? target.querySelector('.page-header') : null;
    if (header?.nextSibling) {
        target.insertBefore(banner, header.nextSibling);
    } else if (target) {
        target.insertBefore(banner, target.firstChild);
    }

}
