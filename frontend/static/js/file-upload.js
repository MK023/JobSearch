/**
 * Interview file upload module.
 * Handles presigned URL flow: request URL -> PUT to R2 -> confirm -> optional scan.
 */

const FileUpload = {
    interviewId: null,
    fileListEl: null,

    init(interviewId) {
        this.interviewId = interviewId;
        this.fileListEl = document.getElementById('file-list');
        if (!this.fileListEl) return;
        this.loadFiles();
        this._bindUploadButton();
    },

    _bindUploadButton() {
        const btn = document.getElementById('btn-upload-file');
        if (!btn) return;

        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.pdf,.docx,.doc,.txt,.xlsx,.xls';
        input.style.display = 'none';
        document.body.appendChild(input);

        btn.addEventListener('click', () => input.click());
        input.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) this.uploadFile(file);
            input.value = '';
        });
    },

    async loadFiles() {
        try {
            const resp = await fetch('/api/v1/files/interview/' + this.interviewId);
            const data = await resp.json();
            this._renderFiles(data.files || []);
        } catch (err) {
            console.error('Failed to load files:', err);
        }
    },

    _validateFile(file) {
        const allowedTypes = [
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/vnd.ms-excel',
            'text/plain',
        ];
        if (!allowedTypes.includes(file.type)) {
            if (typeof showToast === 'function') showToast('Tipo file non supportato. Usa PDF, DOCX, DOC, TXT o XLSX.', 'error');
            return false;
        }
        if (file.size > 10 * 1024 * 1024) {
            if (typeof showToast === 'function') showToast('File troppo grande. Massimo 10 MB.', 'error');
            return false;
        }
        return true;
    },

    async _requestPresignedUrl(file) {
        try {
            const resp = await fetch('/api/v1/files/request-upload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    interview_id: this.interviewId,
                    filename: file.name,
                    content_type: file.type,
                }),
            });
            const data = await resp.json();
            if (!resp.ok) {
                if (typeof showToast === 'function') showToast(data.error || 'Errore nella richiesta di upload', 'error');
                return null;
            }
            return data;
        } catch (err) {
            console.error('requestPresignedUrl error:', err);
            if (typeof showToast === 'function') showToast('Errore di rete. Riprova.', 'error');
            return null;
        }
    },

    async _putToR2(uploadUrl, file) {
        try {
            const putResp = await fetch(uploadUrl, {
                method: 'PUT',
                headers: { 'Content-Type': file.type },
                body: file,
            });
            if (!putResp.ok) {
                throw new Error('R2 upload failed: ' + putResp.status);
            }
            return true;
        } catch (err) {
            console.error('putToR2 error:', err);
            if (typeof showToast === 'function') showToast('Upload fallito. Riprova.', 'error');
            return false;
        }
    },

    async _confirmUpload(fileId) {
        try {
            const resp = await fetch('/api/v1/files/' + fileId + '/confirm', { method: 'POST' });
            if (!resp.ok) {
                const errData = await resp.json();
                if (typeof showToast === 'function') showToast(errData.error || 'Conferma upload fallita', 'error');
                return false;
            }
            return true;
        } catch (err) {
            console.error('confirmUpload error:', err);
            if (typeof showToast === 'function') showToast('Errore nella conferma. Il file potrebbe essere stato caricato.', 'error');
            return false;
        }
    },

    async uploadFile(file) {
        if (!this._validateFile(file)) return;

        this._showUploadProgress(file.name);
        const uploadData = await this._requestPresignedUrl(file);
        if (!uploadData) { this._hideUploadProgress(); return; }

        const putOk = await this._putToR2(uploadData.upload_url, file);
        if (!putOk) { this._hideUploadProgress(); return; }

        const confirmOk = await this._confirmUpload(uploadData.file_id);
        this._hideUploadProgress();
        if (!confirmOk) return;

        this.loadFiles();
    },

    async scanFile(fileId) {
        const btn = document.querySelector('[data-scan-id="' + fileId + '"]');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Scansione...';
        }

        try {
            const resp = await fetch('/api/v1/files/' + fileId + '/scan', { method: 'POST' });
            const data = await resp.json();
            if (!resp.ok) {
                if (typeof showToast === 'function') showToast(data.error || 'Scansione fallita', 'error');
            }
        } catch (err) {
            console.error('scanFile error:', err);
            if (typeof showToast === 'function') showToast('Errore nella scansione. Riprova.', 'error');
        }

        this.loadFiles();
    },

    async deleteFile(fileId) {
        if (!confirm('Eliminare questo file?')) return;

        try {
            const resp = await fetch('/api/v1/files/' + fileId, { method: 'DELETE' });
            if (!resp.ok) {
                const data = await resp.json();
                if (typeof showToast === 'function') showToast(data.error || 'Eliminazione fallita', 'error');
                return;
            }
        } catch (err) {
            console.error('deleteFile error:', err);
            if (typeof showToast === 'function') showToast('Errore nella eliminazione. Riprova.', 'error');
            return;
        }

        this.loadFiles();
    },

    _renderFiles(files) {
        if (!this.fileListEl) return;

        if (files.length === 0) {
            this.fileListEl.textContent = '';
            const p = document.createElement('p');
            p.className = 'file-list-loading';
            p.style.fontStyle = 'italic';
            p.textContent = 'Nessun file caricato.';
            this.fileListEl.appendChild(p);
            return;
        }

        this.fileListEl.textContent = '';
        files.forEach(f => {
            const row = document.createElement('div');
            row.className = 'file-row';

            const left = document.createElement('div');
            left.className = 'file-row-info';

            const nameP = document.createElement('p');
            nameP.className = 'file-row-name';
            nameP.textContent = f.original_filename;
            left.appendChild(nameP);

            const metaDiv = document.createElement('div');
            metaDiv.className = 'file-row-meta';

            const badge = document.createElement('span');
            const statusInfo = {
                pending: { label: 'In attesa', cls: 'file-status-pending' },
                uploaded: { label: 'Caricato', cls: 'file-status-uploaded' },
                compiled: { label: 'Compilato', cls: 'file-status-compiled' },
                not_compiled: { label: 'Non compilato', cls: 'file-status-error' },
                scan_error: { label: 'Errore scansione', cls: 'file-status-error' },
            }[f.status] || { label: f.status, cls: 'file-status-pending' };
            badge.className = 'file-status ' + statusInfo.cls;
            badge.textContent = statusInfo.label;
            metaDiv.appendChild(badge);

            const sizeSpan = document.createElement('span');
            sizeSpan.className = 'file-row-size';
            sizeSpan.textContent = f.file_size ? Math.round(f.file_size / 1024) + ' KB' : '-';
            metaDiv.appendChild(sizeSpan);
            left.appendChild(metaDiv);

            if (f.scan_result) {
                const scanP = document.createElement('p');
                scanP.className = 'file-row-scan';
                scanP.textContent = f.scan_result;
                left.appendChild(scanP);
            }

            row.appendChild(left);

            const right = document.createElement('div');
            right.className = 'file-row-actions';

            const canScan = f.status === 'uploaded' || f.status === 'scan_error';
            if (canScan) {
                const scanBtn = document.createElement('button');
                scanBtn.dataset.scanId = f.id;
                scanBtn.className = 'btn btn-ghost btn-sm';
                scanBtn.textContent = 'Scansiona';
                scanBtn.addEventListener('click', () => FileUpload.scanFile(f.id));
                right.appendChild(scanBtn);
            }

            if (f.download_url) {
                const dlLink = document.createElement('a');
                dlLink.href = f.download_url;
                dlLink.target = '_blank';
                dlLink.rel = 'noopener noreferrer';
                dlLink.className = 'btn btn-ghost btn-sm';
                dlLink.textContent = 'Scarica';
                right.appendChild(dlLink);
            }

            const delBtn = document.createElement('button');
            delBtn.className = 'btn btn-danger btn-sm';
            delBtn.textContent = 'Elimina';
            delBtn.addEventListener('click', () => FileUpload.deleteFile(f.id));
            right.appendChild(delBtn);

            row.appendChild(right);
            this.fileListEl.appendChild(row);
        });
    },

    _showUploadProgress(filename) {
        const el = document.getElementById('upload-progress');
        if (el) {
            el.classList.remove('hidden');
            const nameEl = el.querySelector('.upload-filename');
            if (nameEl) nameEl.textContent = filename;
        }
    },

    _hideUploadProgress() {
        const el = document.getElementById('upload-progress');
        if (el) el.classList.add('hidden');
    },
};
