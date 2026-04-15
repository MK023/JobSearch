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
            if (window.location.pathname.indexOf('/analysis/') !== -1) {
                setTimeout(function() {
                    var ref = document.referrer;
                    if (ref && ref.indexOf('/interviews') !== -1) {
                        window.location.href = '/interviews';
                    } else {
                        window.location.reload();
                    }
                }, 1200);
            }
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


function logRoundOutcome(interviewId, outcome, analysisId) {
    var confirmMsg = {
        passed: 'Confermi di aver superato questo round? Potrai poi scegliere il prossimo step.',
        rejected: 'Confermi l\'esito "scartato"? L\'analisi passera\' a stato scartato.',
        withdrawn: 'Confermi di aver ritirato la candidatura? L\'analisi passera\' a stato scartato.'
    }[outcome];
    if (!confirm(confirmMsg)) return;

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
        if (outcome === 'passed') {
            promptNextRound(analysisId);
        } else {
            window.location.reload();
        }
    })
    .catch(function(e) {
        console.error('logRoundOutcome error:', e);
        showToast('Errore salvataggio esito', 'error');
    });
}


function promptNextRound(analysisId) {
    var answer = window.prompt(
        'Prossimo step?\n\n  tecnico\n  hr\n  conoscitivo\n  finale\n  offerta  (= arrivata offerta, chiude il processo)\n\nLascia vuoto per restare a "colloquio" senza nuovo round.',
        'tecnico'
    );
    if (answer === null) { window.location.reload(); return; }
    var choice = (answer || '').trim().toLowerCase();
    if (choice === '') { window.location.reload(); return; }

    if (choice === 'offerta') {
        fetch('/api/v1/status/' + analysisId + '/offerta', {
            method: 'POST',
            headers: { 'Accept': 'application/json' }
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.ok) {
                showToast('Offerta registrata!', 'success');
                window.location.reload();
            } else {
                showToast(data.error || 'Errore', 'error');
            }
        });
        return;
    }

    var validTypes = ['tecnico', 'hr', 'conoscitivo', 'finale', 'other'];
    if (validTypes.indexOf(choice) === -1) {
        showToast('Tipo non valido: ' + choice, 'error');
        return;
    }

    var whenStr = window.prompt(
        'Quando e\' previsto il prossimo round?\n\nFormato: YYYY-MM-DD HH:MM (es: 2026-04-22 14:30)\n\nSe non lo sai ancora, scrivi una data fittizia e la aggiorni dopo con "Modifica".',
        ''
    );
    if (!whenStr) { showToast('Round annullato', 'info'); window.location.reload(); return; }

    var scheduled = parseScheduledAt(whenStr);
    if (!scheduled) {
        showToast('Formato data non valido', 'error');
        return;
    }

    fetch('/api/v1/interviews/' + analysisId + '/next-round', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ scheduled_at: scheduled, interview_type: choice })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            showToast('Round ' + data.round_number + ' creato', 'success');
            window.location.reload();
        } else {
            showToast(data.error || 'Errore creazione round', 'error');
        }
    })
    .catch(function(e) {
        console.error('nextRound error:', e);
        showToast('Errore di rete', 'error');
    });
}


function parseScheduledAt(s) {
    var m = /^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})$/.exec(s.trim());
    if (!m) return null;
    var y = parseInt(m[1], 10), mo = parseInt(m[2], 10), d = parseInt(m[3], 10);
    var h = parseInt(m[4], 10), mi = parseInt(m[5], 10);
    if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59) return null;
    var dt = new Date(y, mo - 1, d, h, mi, 0);
    return dt.toISOString();
}
