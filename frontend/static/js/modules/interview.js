/**
 * Interview modal: open, close, submit, populate.
 * Uses flatpickr for date/time input (Italian locale, dark theme).
 * Platform-based dynamic fields.
 */

var fpScheduled = null;
var fpEnds = null;

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


function destroyFlatpickrInstances() {
    if (fpScheduled) { fpScheduled.destroy(); fpScheduled = null; }
    if (fpEnds) { fpEnds.destroy(); fpEnds = null; }
}


function closeInterviewModal() {
    var modal = document.getElementById('interview-modal');
    modal.classList.add('hidden');
    destroyFlatpickrInstances();
    resetInterviewForm();
}


function resetInterviewForm() {
    document.getElementById('interview-form').reset();
    document.getElementById('iv-analysis-id').value = '';
    // Reset dynamic fields visibility
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

    // Update dynamic fields after populating platform
    togglePlatformFields();
}


function isoToLocalInput(iso) {
    // Extract YYYY-MM-DDTHH:MM from ISO string, ignoring any timezone offset
    return iso.substring(0, 16);
}


function submitInterview(e) {
    e.preventDefault();

    var analysisId = document.getElementById('iv-analysis-id').value;
    var scheduled = document.getElementById('iv-scheduled').value;
    if (!scheduled) return false;

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
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            closeInterviewModal();
            // Update status toggle
            var group = document.querySelector('[data-analysis-id="' + analysisId + '"]');
            if (group) {
                group.querySelectorAll('.status-option').forEach(function(b) {
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
                    stEl.className = 'status-badge status-colloquio';
                    stEl.textContent = 'COLLOQUIO';
                }
            }
            if (typeof refreshHistoryCounts === 'function') refreshHistoryCounts();
            if (typeof refreshSpending === 'function') refreshSpending();
            if (typeof refreshDashboard === 'function') refreshDashboard();
            showToast('Colloquio salvato', 'success');
            // Reload current page to reflect changes
            setTimeout(function() {
                window.location.reload();
            }, 1200);
        }
    })
    .catch(function(e) {
        console.error('submitInterview error:', e);
        showToast('Errore salvataggio colloquio', 'error');
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
