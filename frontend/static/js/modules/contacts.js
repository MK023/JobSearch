/**
 * Recruiter contacts: toggle, load, save, delete.
 */

function toggleContacts(id) {
    var el = document.getElementById('contacts-' + id);
    if (!el) return;

    if (el.classList.contains('hidden')) {
        el.classList.remove('hidden');
        loadContacts(id);
    } else {
        el.classList.add('hidden');
    }
}

function loadContacts(id) {
    fetch('/api/v1/contacts/' + id)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var list = document.getElementById('contacts-list-' + id);
            if (!list) return;

            while (list.firstChild) list.removeChild(list.firstChild);

            (data.contacts || []).forEach(function(c) {
                var row = document.createElement('div');
                row.className = 'contact-row';

                var name = document.createElement('span');
                name.className = 'contact-name';
                name.textContent = c.name || 'Senza nome';
                row.appendChild(name);

                var detail = document.createElement('span');
                detail.className = 'contact-detail';
                var parts = [];
                if (c.email) parts.push(c.email);
                if (c.phone) parts.push(c.phone);
                if (c.notes) parts.push(c.notes);
                detail.textContent = parts.join(' \u00b7 ');
                row.appendChild(detail);

                if (c.linkedin_url) {
                    var lnk = document.createElement('a');
                    lnk.href = c.linkedin_url;
                    lnk.target = '_blank';
                    lnk.rel = 'noopener noreferrer';
                    lnk.textContent = '\uD83D\uDCBC LinkedIn';
                    lnk.className = 'link-subtle';
                    row.appendChild(lnk);
                }

                var del = document.createElement('button');
                del.className = 'btn btn-danger btn-sm';
                del.textContent = '\uD83D\uDDD1\uFE0F';
                del.onclick = function() { deleteContact(String(c.id), id); };
                row.appendChild(del);

                list.appendChild(row);
            });
        })
        .catch(function(e) {
        console.error('loadContacts error:', e);
        showToast('Errore caricamento contatti', 'error');
    });
}

function saveContact(analysisId) {
    var fd = new FormData();
    fd.append('analysis_id', analysisId);
    fd.append('name', document.getElementById('ct-name-' + analysisId).value);
    fd.append('email', document.getElementById('ct-email-' + analysisId).value);
    fd.append('phone', document.getElementById('ct-phone-' + analysisId).value);
    fd.append('company', document.getElementById('ct-company-' + analysisId).value);
    fd.append('linkedin_url', document.getElementById('ct-linkedin-' + analysisId).value);
    fd.append('notes', document.getElementById('ct-notes-' + analysisId).value);

    fetch('/api/v1/contacts', { method: 'POST', body: fd })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.ok) {
                loadContacts(analysisId);
                ['name', 'email', 'phone', 'linkedin', 'notes'].forEach(function(f) {
                    var el = document.getElementById('ct-' + f + '-' + analysisId);
                    if (el && f !== 'company') el.value = '';
                });
                showToast('Contatto aggiunto', 'success');
            }
        })
        .catch(function(e) {
            console.error('saveContact error:', e);
            showToast('Errore salvataggio contatto', 'error');
        });
}

function deleteContact(contactId, analysisId) {
    fetch('/api/v1/contacts/' + contactId, { method: 'DELETE' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.ok) {
                loadContacts(analysisId);
                showToast('Contatto eliminato', 'success');
            }
        })
        .catch(function(e) {
            console.error('deleteContact error:', e);
            showToast('Errore eliminazione contatto', 'error');
        });
}
