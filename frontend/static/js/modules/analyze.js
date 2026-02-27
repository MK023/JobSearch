/**
 * AJAX analysis submission — replaces blocking form POST.
 * Shows spinner via Alpine state, redirects to result on success.
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

    fetch('/api/v1/analyze', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: JSON.stringify({
            job_description: jobDesc,
            job_url: jobUrl,
            model: model
        })
    })
    .then(function(r) {
        if (r.status === 429) {
            showToast('Troppe richieste, riprova tra poco', 'error');
            resetLoading(wrapper);
            return null;
        }
        return r.json();
    })
    .then(function(data) {
        if (!data) return;
        if (data.error) {
            showToast(data.error, 'error');
            resetLoading(wrapper);
        } else if (data.redirect) {
            window.location.href = data.redirect;
        }
    })
    .catch(function() {
        showToast('Errore di rete', 'error');
        resetLoading(wrapper);
    });

    return false;
}

function resetLoading(wrapper) {
    if (wrapper && typeof Alpine !== 'undefined') {
        try { Alpine.$data(wrapper).analyzeLoading = false; } catch (_) {}
    }
}
