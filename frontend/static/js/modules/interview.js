/**
 * Interview modal: open, close, submit, populate.
 */

function openInterviewModal(analysisId) {
    var modal = document.getElementById('interview-modal');
    document.getElementById('iv-analysis-id').value = analysisId;
    document.getElementById('interview-modal-title').textContent = 'Prenota colloquio';

    // Try to load existing interview data
    fetch('/api/v1/interviews/' + analysisId, {
        headers: { 'Accept': 'application/json' }
    })
    .then(function(r) {
        if (r.ok) return r.json();
        return null;
    })
    .then(function(data) {
        if (data && data.scheduled_at) {
            populateInterviewForm(data);
            document.getElementById('interview-modal-title').textContent = 'Modifica colloquio';
        }
        modal.style.display = 'flex';
    })
    .catch(function() {
        modal.style.display = 'flex';
    });
}


function closeInterviewModal() {
    var modal = document.getElementById('interview-modal');
    modal.style.display = 'none';
    resetInterviewForm();
}


function resetInterviewForm() {
    document.getElementById('interview-form').reset();
    document.getElementById('iv-analysis-id').value = '';
}


function populateInterviewForm(data) {
    if (data.scheduled_at) {
        document.getElementById('iv-scheduled').value = isoToLocalInput(data.scheduled_at);
    }
    if (data.ends_at) {
        document.getElementById('iv-ends').value = isoToLocalInput(data.ends_at);
    }
    if (data.interview_type) document.getElementById('iv-type').value = data.interview_type;
    if (data.recruiter_name) document.getElementById('iv-recruiter-name').value = data.recruiter_name;
    if (data.recruiter_email) document.getElementById('iv-recruiter-email').value = data.recruiter_email;
    if (data.meeting_link) document.getElementById('iv-meeting-link').value = data.meeting_link;
    if (data.phone_number) document.getElementById('iv-phone').value = data.phone_number;
    if (data.phone_pin) document.getElementById('iv-pin').value = data.phone_pin;
    if (data.location) document.getElementById('iv-location').value = data.location;
    if (data.notes) document.getElementById('iv-notes').value = data.notes;
}


function isoToLocalInput(iso) {
    // Convert ISO string to datetime-local input value (YYYY-MM-DDTHH:MM)
    var d = new Date(iso);
    var pad = function(n) { return n < 10 ? '0' + n : n; };
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
           'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}


function submitInterview(e) {
    e.preventDefault();

    var analysisId = document.getElementById('iv-analysis-id').value;
    var scheduled = document.getElementById('iv-scheduled').value;
    if (!scheduled) return false;

    var payload = {
        scheduled_at: new Date(scheduled).toISOString(),
        ends_at: null,
        interview_type: document.getElementById('iv-type').value || null,
        recruiter_name: document.getElementById('iv-recruiter-name').value || null,
        recruiter_email: document.getElementById('iv-recruiter-email').value || null,
        meeting_link: document.getElementById('iv-meeting-link').value || null,
        phone_number: document.getElementById('iv-phone').value || null,
        phone_pin: document.getElementById('iv-pin').value || null,
        location: document.getElementById('iv-location').value || null,
        notes: document.getElementById('iv-notes').value || null
    };

    var endsVal = document.getElementById('iv-ends').value;
    if (endsVal) {
        payload.ends_at = new Date(endsVal).toISOString();
    }

    fetch('/api/v1/interviews/' + analysisId, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: JSON.stringify(payload)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            closeInterviewModal();
            // Update pill buttons
            var group = document.querySelector('[data-analysis-id="' + analysisId + '"]');
            if (group) {
                group.querySelectorAll('.pill-btn').forEach(function(b) {
                    b.classList.remove('active');
                });
                var collBtn = group.querySelector('[data-status="colloquio"]');
                if (collBtn) collBtn.classList.add('active');
            }
            // Update history item
            var histItem = document.querySelector('[data-hist-id="' + analysisId + '"]');
            if (histItem) {
                histItem.dataset.histStatus = 'colloquio';
                var stEl = histItem.querySelector('.status-badge');
                if (stEl) {
                    stEl.className = 'status-badge status-badge-colloquio';
                    stEl.textContent = '\uD83D\uDDE3\uFE0F colloquio';
                }
            }
            refreshHistoryCounts();
            refreshSpending();
            refreshDashboard();
            // Reload page if on detail view to show interview card
            if (window.location.pathname.indexOf('/analysis/') !== -1) {
                window.location.reload();
            }
        }
    })
    .catch(function(e) { console.error('submitInterview error:', e); });

    return false;
}


function deleteInterviewFromDetail(analysisId) {
    if (!confirm('Rimuovere il colloquio? Lo status tornera\' a "candidato".')) return;

    fetch('/api/v1/interviews/' + analysisId, {
        method: 'DELETE',
        headers: { 'Accept': 'application/json' }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            window.location.reload();
        }
    })
    .catch(function(e) { console.error('deleteInterview error:', e); });
}
