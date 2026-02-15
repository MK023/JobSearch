/**
 * Follow-up email and LinkedIn message generation.
 */

function _createGenBox(label, id) {
    // Try followup alerts area first, then dashboard area
    var area = document.getElementById('generated-area-' + id)
            || document.getElementById('dash-generated-area-' + id);
    if (!area) {
        var alertEl = document.getElementById('followup-' + id);
        if (alertEl) {
            area = document.createElement('div');
            area.id = 'generated-area-' + id;
            alertEl.parentNode.insertBefore(area, alertEl.nextSibling);
        } else {
            return null;
        }
    }
    while (area.firstChild) area.removeChild(area.firstChild);

    var box = document.createElement('div');
    box.className = 'generated-box';

    var lbl = document.createElement('div');
    lbl.className = 'generated-label';
    lbl.textContent = label;
    box.appendChild(lbl);

    area.appendChild(box);
    return { area: area, box: box };
}

function _addGenText(parent, text, elId) {
    var d = document.createElement('div');
    d.className = 'generated-text';
    d.textContent = text;
    if (elId) d.id = elId;
    parent.appendChild(d);
    return d;
}

function _addCopyBtn(parent, targetId) {
    var btn = document.createElement('button');
    btn.className = 'btn btn-muted btn-sm';
    btn.textContent = '\uD83D\uDCCB Copia';
    btn.onclick = function() {
        navigator.clipboard.writeText(document.getElementById(targetId).textContent);
    };
    parent.appendChild(btn);
}

function _addGenMeta(parent, cost, tokens, extra) {
    var m = document.createElement('div');
    m.className = 'generated-meta';
    m.textContent = '\uD83D\uDCB0 $' + (cost || 0).toFixed(5) +
        ' | ' + (tokens || 0) + ' tok' +
        (extra ? ' \u00b7 ' + extra : '');
    parent.appendChild(m);
}


function genFollowup(id) {
    var g = _createGenBox('\u23F3 Generazione email follow-up...', id);
    if (!g) return;

    var fd = new FormData();
    fd.append('analysis_id', id);
    fd.append('language', 'italiano');

    fetch('/api/v1/followup-email', { method: 'POST', body: fd })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            while (g.box.firstChild) g.box.removeChild(g.box.firstChild);

            if (data.error) {
                var errLbl = document.createElement('div');
                errLbl.className = 'generated-label';
                errLbl.textContent = '\u274C Errore';
                g.box.appendChild(errLbl);
                _addGenText(g.box, data.error);
                return;
            }

            var lbl = document.createElement('div');
            lbl.className = 'generated-label';
            lbl.textContent = '\u2709\uFE0F Email di follow-up';
            g.box.appendChild(lbl);

            var subj = document.createElement('div');
            subj.className = 'generated-text';
            subj.style.fontWeight = '600';
            subj.textContent = 'Oggetto: ' + data.subject;
            g.box.appendChild(subj);

            _addGenText(g.box, data.body, 'followup-body-' + id);
            _addCopyBtn(g.box, 'followup-body-' + id);
            _addGenMeta(g.box, data.cost_usd, (data.tokens || {}).total);
            refreshSpending();
        })
        .catch(function(e) {
            while (g.box.firstChild) g.box.removeChild(g.box.firstChild);
            var errLbl = document.createElement('div');
            errLbl.className = 'generated-label';
            errLbl.textContent = '\u274C Errore di rete';
            g.box.appendChild(errLbl);
            console.error('genFollowup error:', e);
        });
}


function genLinkedin(id) {
    var g = _createGenBox('\u23F3 Generazione messaggio LinkedIn...', id);
    if (!g) return;

    var fd = new FormData();
    fd.append('analysis_id', id);
    fd.append('language', 'italiano');

    fetch('/api/v1/linkedin-message', { method: 'POST', body: fd })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            while (g.box.firstChild) g.box.removeChild(g.box.firstChild);

            if (data.error) {
                var errLbl = document.createElement('div');
                errLbl.className = 'generated-label';
                errLbl.textContent = '\u274C Errore';
                g.box.appendChild(errLbl);
                _addGenText(g.box, data.error);
                return;
            }

            var lbl = document.createElement('div');
            lbl.className = 'generated-label';
            lbl.textContent = '\uD83D\uDCBC Messaggio LinkedIn';
            g.box.appendChild(lbl);

            _addGenText(g.box, data.message, 'linkedin-msg-' + id);
            _addCopyBtn(g.box, 'linkedin-msg-' + id);

            if (data.connection_note) {
                var lbl2 = document.createElement('div');
                lbl2.className = 'generated-label';
                lbl2.style.marginTop = '8px';
                lbl2.textContent = '\uD83E\uDD1D Nota connessione';
                g.box.appendChild(lbl2);

                _addGenText(g.box, data.connection_note, 'linkedin-conn-' + id);
                _addCopyBtn(g.box, 'linkedin-conn-' + id);
            }

            if (data.approach_tip) {
                _addGenMeta(g.box, 0, 0, data.approach_tip);
            }
            _addGenMeta(g.box, data.cost_usd, (data.tokens || {}).total);
            refreshSpending();
        })
        .catch(function(e) {
            while (g.box.firstChild) g.box.removeChild(g.box.firstChild);
            var errLbl = document.createElement('div');
            errLbl.className = 'generated-label';
            errLbl.textContent = '\u274C Errore di rete';
            g.box.appendChild(errLbl);
            console.error('genLinkedin error:', e);
        });
}


function markFollowupDone(id) {
    fetch('/api/v1/followup-done/' + id, { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.ok) {
                var el = document.getElementById('followup-' + id);
                if (el) el.remove();
                // Also remove associated generated area
                var genArea = document.getElementById('generated-area-' + id);
                if (genArea) genArea.remove();
                refreshDashboard();
            }
        })
        .catch(function(e) { console.error('markFollowupDone error:', e); });
}
