/**
 * Interview modal: open, close, submit, populate.
 * Uses flatpickr for date/time input (Italian locale, dark theme).
 * Platform-based dynamic fields.
 */

let fpScheduled = null;
let fpEnds = null;
let _isNewRoundMode = false;

/**
 * Platform → visible fields mapping.
 * Fields not listed are hidden for that platform.
 */
const PLATFORM_FIELDS = {
    google_meet: ['fg-meeting-link', 'fg-phone', 'fg-pin'],
    teams: ['fg-meeting-link', 'fg-meeting-id', 'fg-pin'],
    zoom: ['fg-meeting-link', 'fg-pin'],
    phone: ['fg-phone', 'fg-pin'],
    in_person: ['fg-location'],
    other: ['fg-meeting-link', 'fg-phone', 'fg-pin', 'fg-location']
};

const ALL_PLATFORM_FIELDS = ['fg-meeting-link', 'fg-meeting-id', 'fg-phone', 'fg-pin', 'fg-location'];


function togglePlatformFields() {
    const platform = document.getElementById('iv-platform').value;
    const visible = platform ? (PLATFORM_FIELDS[platform] || []) : ALL_PLATFORM_FIELDS;

    ALL_PLATFORM_FIELDS.forEach(function(id) {
        const el = document.getElementById(id);
        if (el) {
            el.style.display = visible.includes(id) ? '' : 'none';
        }
    });
}


function openInterviewModal(analysisId) {
    _isNewRoundMode = false;
    const modal = document.getElementById('interview-modal');
    document.getElementById('iv-analysis-id').value = analysisId;
    document.getElementById('interview-modal-title').textContent = 'Prenota colloquio';

    // Initialize flatpickr date/time pickers
    destroyFlatpickrInstances();
    const fpConfig = {
        enableTime: true,
        time_24hr: true,
        dateFormat: "Y-m-dTH:i",
        altInput: true,
        altFormat: "l j F Y, H:i",
        locale: "it",
        minDate: "today"
    };
    fpScheduled = flatpickr('#iv-scheduled', { ...fpConfig });
    fpEnds = flatpickr('#iv-ends', { ...fpConfig, minDate: null });

    // Show all fields by default (no platform selected)
    togglePlatformFields();

    // Try to load existing interview data
    fetch('/api/v1/interviews/' + analysisId, {
        headers: { 'Accept': 'application/json' }
    })
    .then(function(r) {
        if (r.ok) return r.json();
        return null;
    })
    .then(function(data) {
        if (data?.scheduled_at) {
            populateInterviewForm(data);
            document.getElementById('interview-modal-title').textContent = 'Modifica colloquio';
        }
        modal.classList.remove('hidden');
    })
    .catch(function() {
        modal.classList.remove('hidden');
    });
}


function openNewRoundModal(analysisId) {
    _isNewRoundMode = true;
    const modal = document.getElementById('interview-modal');
    document.getElementById('iv-analysis-id').value = analysisId;
    document.getElementById('interview-modal-title').textContent = 'Nuovo round';

    destroyFlatpickrInstances();
    resetInterviewForm();

    const fpConfig = {
        enableTime: true,
        time_24hr: true,
        dateFormat: "Y-m-dTH:i",
        altInput: true,
        altFormat: "l j F Y, H:i",
        locale: "it",
        minDate: "today"
    };
    fpScheduled = flatpickr('#iv-scheduled', { ...fpConfig });
    fpEnds = flatpickr('#iv-ends', { ...fpConfig, minDate: null });

    togglePlatformFields();
    document.getElementById('iv-analysis-id').value = analysisId;
    modal.classList.remove('hidden');
}


function destroyFlatpickrInstances() {
    if (fpScheduled) { fpScheduled.destroy(); fpScheduled = null; }
    if (fpEnds) { fpEnds.destroy(); fpEnds = null; }
}


function closeInterviewModal() {
    const modal = document.getElementById('interview-modal');
    modal.classList.add('hidden');
    _isNewRoundMode = false;
    destroyFlatpickrInstances();
    resetInterviewForm();
}


function resetInterviewForm() {
    document.getElementById('interview-form').reset();
    document.getElementById('iv-analysis-id').value = '';
    togglePlatformFields();
}


function populateInterviewForm(data) {
    if (data.scheduled_at && fpScheduled) {
        fpScheduled.setDate(isoToLocalInput(data.scheduled_at), true, "Y-m-dTH:i");
    }
    if (data.ends_at && fpEnds) {
        fpEnds.setDate(isoToLocalInput(data.ends_at), true, "Y-m-dTH:i");
    }
    if (data.platform) document.getElementById('iv-platform').value = data.platform;
    if (data.interview_type) document.getElementById('iv-type').value = data.interview_type;
    if (data.interviewer_name) document.getElementById('iv-interviewer-name').value = data.interviewer_name;
    if (data.recruiter_name) document.getElementById('iv-recruiter-name').value = data.recruiter_name;
    if (data.recruiter_email) document.getElementById('iv-recruiter-email').value = data.recruiter_email;
    if (data.meeting_link) document.getElementById('iv-meeting-link').value = data.meeting_link;
    if (data.meeting_id) document.getElementById('iv-meeting-id').value = data.meeting_id;
    if (data.phone_number) document.getElementById('iv-phone').value = data.phone_number;
    if (data.access_pin) document.getElementById('iv-pin').value = data.access_pin;
    if (data.location) document.getElementById('iv-location').value = data.location;
    if (data.notes) document.getElementById('iv-notes').value = data.notes;

    togglePlatformFields();
}


function _pad2(n) {
    return String(n).padStart(2, '0');
}

function isoToLocalInput(iso) {
    const d = new Date(iso);
    return d.getFullYear() + '-' + _pad2(d.getMonth()+1) + '-' + _pad2(d.getDate())
           + 'T' + _pad2(d.getHours()) + ':' + _pad2(d.getMinutes());
}


function _markStatusToggleAsColloquio(analysisId) {
    const group = document.querySelector('[data-analysis-id="' + analysisId + '"]');
    if (!group) return;
    group.querySelectorAll('.status-option').forEach(function(b) {
        b.classList.remove('active');
    });
    const collBtn = group.querySelector('[data-status="colloquio"]');
    if (collBtn) collBtn.classList.add('active');
}

function _markHistoryRowAsColloquio(analysisId) {
    const histItem = document.querySelector('[data-hist-id="' + analysisId + '"]');
    if (!histItem) return;
    histItem.dataset.histStatus = 'colloquio';
    const stEl = histItem.querySelector('.status-badge');
    if (stEl) {
        stEl.className = 'status-badge status-colloquio';
        stEl.textContent = 'COLLOQUIO';
    }
}

function _onInterviewSaved(analysisId) {
    closeInterviewModal();
    _markStatusToggleAsColloquio(analysisId);
    _markHistoryRowAsColloquio(analysisId);
    if (typeof refreshHistoryCounts === 'function') refreshHistoryCounts();
    if (typeof refreshSpending === 'function') refreshSpending();
    showToast('Colloquio salvato', 'success');
    // Reload once; any analysis/interviews detail view refreshes after the toast.
    const path = globalThis.location.pathname;
    if (path.includes('/analysis/') || path.includes('/interviews')) {
        setTimeout(function() { globalThis.location.reload(); }, 800);
    } else {
        globalThis.location.reload();
    }
}

function submitInterview(e) {
    e.preventDefault();

    const analysisId = document.getElementById('iv-analysis-id').value;
    const scheduled = document.getElementById('iv-scheduled').value;
    if (!scheduled) return false;

    if (_isNewRoundMode) {
        return submitNewRound(analysisId, scheduled);
    }

    // Only send values from visible platform-dependent fields
    const platform = document.getElementById('iv-platform').value || null;
    const visible = platform ? (PLATFORM_FIELDS[platform] || []) : ALL_PLATFORM_FIELDS;

    function visibleVal(fieldGroupId, inputId) {
        return visible.includes(fieldGroupId)
            ? (document.getElementById(inputId).value || null)
            : null;
    }

    const payload = {
        scheduled_at: scheduled,
        ends_at: null,
        platform: platform,
        interview_type: document.getElementById('iv-type').value || null,
        interviewer_name: document.getElementById('iv-interviewer-name').value || null,
        recruiter_name: document.getElementById('iv-recruiter-name').value || null,
        recruiter_email: document.getElementById('iv-recruiter-email').value || null,
        meeting_link: visibleVal('fg-meeting-link', 'iv-meeting-link'),
        meeting_id: visibleVal('fg-meeting-id', 'iv-meeting-id'),
        phone_number: visibleVal('fg-phone', 'iv-phone'),
        access_pin: visibleVal('fg-pin', 'iv-pin'),
        location: visibleVal('fg-location', 'iv-location'),
        notes: document.getElementById('iv-notes').value || null
    };

    const endsVal = document.getElementById('iv-ends').value;
    if (endsVal) {
        payload.ends_at = endsVal;
    }

    fetch('/api/v1/interviews/' + analysisId, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: JSON.stringify(payload)
    })
    .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
    .then(function(res) {
        if (res.status >= 400 || res.data.error) {
            showToast(res.data.error || 'Errore salvataggio colloquio', 'error');
            return;
        }
        if (res.data.ok) _onInterviewSaved(analysisId);
    })
    .catch(function(e) {
        console.error('submitInterview error:', e);
        showToast('Errore salvataggio colloquio', 'error');
    });

    return false;
}


function submitNewRound(analysisId, scheduled) {
    const interviewType = document.getElementById('iv-type').value || null;

    fetch('/api/v1/interviews/' + analysisId + '/next-round', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ scheduled_at: scheduled, interview_type: interviewType })
    })
    .then(function(r) { return r.json().then(function(d) { return {status: r.status, data: d}; }); })
    .then(function(res) {
        if (res.status >= 400 || res.data.error) {
            showToast(res.data.error || 'Errore creazione round', 'error');
            return;
        }
        closeInterviewModal();
        showToast('Round ' + res.data.round_number + ' creato', 'success');
        setTimeout(function() { globalThis.location.reload(); }, 800);
    })
    .catch(function(e) {
        console.error('submitNewRound error:', e);
        showToast('Errore di rete', 'error');
    });

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
            globalThis.location.reload();
        }
    })
    .catch(function(e) {
        console.error('deleteInterview error:', e);
        showToast('Errore rimozione colloquio', 'error');
    });
}


function logRoundOutcome(interviewId, outcome) {
    fetch('/api/v1/interviews/round/' + interviewId + '/outcome', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ outcome: outcome })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (!data.ok) {
            showToast(data.error || 'Errore', 'error');
            return;
        }
        showToast('Esito salvato', 'success');
        setTimeout(function() { globalThis.location.reload(); }, 800);
    })
    .catch(function(e) {
        console.error('logRoundOutcome error:', e);
        showToast('Errore salvataggio esito', 'error');
    });
}


function markAsOffer(analysisId) {
    fetch('/api/v1/status/' + analysisId + '/offerta', {
        method: 'POST',
        headers: { 'Accept': 'application/json' }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            showToast('Offerta registrata!', 'success');
            setTimeout(function() { globalThis.location.reload(); }, 800);
        } else {
            showToast(data.error || 'Errore', 'error');
        }
    })
    .catch(function(e) {
        console.error('markAsOffer error:', e);
        showToast('Errore di rete', 'error');
    });
}
