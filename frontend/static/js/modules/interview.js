/**
 * Interview modal: open, close, submit, populate.
 * Uses flatpickr for date/time input (Italian locale, dark theme).
 * Platform-based dynamic fields.
 */

var fpScheduled = null;
var fpEnds = null;
var _isNewRoundMode = false;

/**
 * Platform → visible fields mapping.
 * Fields not listed are hidden for that platform.
 */
var PLATFORM_FIELDS = {
    google_meet: ['fg-meeting-link', 'fg-phone', 'fg-pin'],
    teams: ['fg-meeting-link', 'fg-meeting-id', 'fg-pin'],
    zoom: ['fg-meeting-link', 'fg-pin'],
    phone: ['fg-phone', 'fg-pin'],
    in_person: ['fg-location'],
    other: ['fg-meeting-link', 'fg-phone', 'fg-pin', 'fg-location']
};

var ALL_PLATFORM_FIELDS = ['fg-meeting-link', 'fg-meeting-id', 'fg-phone', 'fg-pin', 'fg-location'];


function togglePlatformFields() {
    var platform = document.getElementById('iv-platform').value;
    var visible = platform ? (PLATFORM_FIELDS[platform] || []) : ALL_PLATFORM_FIELDS;

    ALL_PLATFORM_FIELDS.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) {
            el.style.display = visible.indexOf(id) !== -1 ? '' : 'none';
        }
    });
}


function openInterviewModal(analysisId) {
    _isNewRoundMode = false;
    var modal = document.getElementById('interview-modal');
    document.getElementById('iv-analysis-id').value = analysisId;
    document.getElementById('interview-modal-title').textContent = 'Prenota colloquio';

    // Initialize flatpickr date/time pickers
    destroyFlatpickrInstances();
    var fpConfig = {
        enableTime: true,
        time_24hr: true,
        dateFormat: "Y-m-dTH:i",
        altInput: true,
        altFormat: "l j F Y, H:i",
        locale: "it",
        minDate: "today"
    };
    fpScheduled = flatpickr('#iv-scheduled', Object.assign({}, fpConfig));
    fpEnds = flatpickr('#iv-ends', Object.assign({}, fpConfig, { minDate: null }));

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
        if (data && data.scheduled_at) {
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
    var modal = document.getElementById('interview-modal');
    document.getElementById('iv-analysis-id').value = analysisId;
    document.getElementById('interview-modal-title').textContent = 'Nuovo round';

    destroyFlatpickrInstances();
    resetInterviewForm();

    var fpConfig = {
        enableTime: true,
        time_24hr: true,
        dateFormat: "Y-m-dTH:i",
        altInput: true,
        altFormat: "l j F Y, H:i",
        locale: "it",
        minDate: "today"
    };
    fpScheduled = flatpickr('#iv-scheduled', Object.assign({}, fpConfig));
    fpEnds = flatpickr('#iv-ends', Object.assign({}, fpConfig, { minDate: null }));

    togglePlatformFields();
    document.getElementById('iv-analysis-id').value = analysisId;
    modal.classList.remove('hidden');
}


function destroyFlatpickrInstances() {
    if (fpScheduled) { fpScheduled.destroy(); fpScheduled = null; }
    if (fpEnds) { fpEnds.destroy(); fpEnds = null; }
}


function closeInterviewModal() {
    var modal = document.getElementById('interview-modal');
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


function isoToLocalInput(iso) {
    var d = new Date(iso);
    var pad = function(n) { return String(n).padStart(2, '0'); };
    return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate())
           + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}


function submitInterview(e) {
    e.preventDefault();

    var analysisId = document.getElementById('iv-analysis-id').value;
    var scheduled = document.getElementById('iv-scheduled').value;
    if (!scheduled) return false;

    if (_isNewRoundMode) {
        return submitNewRound(analysisId, scheduled);
    }

    // Only send values from visible platform-dependent fields
    var platform = document.getElementById('iv-platform').value || null;
    var visible = platform ? (PLATFORM_FIELDS[platform] || []) : ALL_PLATFORM_FIELDS;

    function visibleVal(fieldGroupId, inputId) {
        return visible.indexOf(fieldGroupId) !== -1
            ? (document.getElementById(inputId).value || null)
            : null;
    }

    var payload = {
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

    var endsVal = document.getElementById('iv-ends').value;
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
        var data = res.data;
        if (data.ok) {
            closeInterviewModal();
            var group = document.querySelector('[data-analysis-id="' + analysisId + '"]');
            if (group) {
                group.querySelectorAll('.status-option').forEach(function(b) {
                    b.classList.remove('active');
                });
                var collBtn = group.querySelector('[data-status="colloquio"]');
                if (collBtn) collBtn.classList.add('active');
            }
            var histItem = document.querySelector('[data-hist-id="' + analysisId + '"]');
            if (histItem) {
                histItem.dataset.histStatus = 'colloquio';
                var stEl = histItem.querySelector('.status-badge');
                if (stEl) {
                    stEl.className = 'status-badge status-colloquio';
                    stEl.textContent = 'COLLOQUIO';
                }
            }
            if (typeof refreshHistoryCounts === 'function') refreshHistoryCounts();
            if (typeof refreshSpending === 'function') refreshSpending();
            if (typeof refreshDashboard === 'function') refreshDashboard();
            showToast('Colloquio salvato', 'success');
            if (window.location.pathname.indexOf('/analysis/') !== -1 ||
                window.location.pathname.indexOf('/interviews') !== -1) {
                setTimeout(function() { window.location.reload(); }, 800);
            }
        }
    })
    .catch(function(e) {
        console.error('submitInterview error:', e);
        showToast('Errore salvataggio colloquio', 'error');
    });

    return false;
}


function submitNewRound(analysisId, scheduled) {
    var interviewType = document.getElementById('iv-type').value || null;

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
        setTimeout(function() { window.location.reload(); }, 800);
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
            window.location.reload();
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
        setTimeout(function() { window.location.reload(); }, 800);
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
            setTimeout(function() { window.location.reload(); }, 800);
        } else {
            showToast(data.error || 'Errore', 'error');
        }
    })
    .catch(function(e) {
        console.error('markAsOffer error:', e);
        showToast('Errore di rete', 'error');
    });
}
