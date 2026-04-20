/**
 * CV file upload handler.
 * Uploads the file directly to the backend for server-side text extraction.
 */

const CV_ALLOWED_EXT = new Set(['.txt', '.pdf', '.doc', '.docx', '.xlsx', '.xls']);
const CV_MAX_SIZE = 10 * 1024 * 1024; // 10 MB

function uploadCV() {
    document.getElementById('cv-file').click();
}

function initCVUpload() {
    const cvFile = document.getElementById('cv-file');
    if (!cvFile) return;

    cvFile.addEventListener('change', function() {
        const file = this.files[0];
        if (!file) return;

        // Validate extension
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (!CV_ALLOWED_EXT.has(ext)) {
            showToast('Formato non supportato. Usa PDF, DOCX, DOC, TXT o XLSX.', 'error');
            this.value = '';
            return;
        }

        // Validate size
        if (file.size > CV_MAX_SIZE) {
            showToast('File troppo grande (max 10 MB).', 'error');
            this.value = '';
            return;
        }

        // Submit file via form with enctype multipart
        const form = document.querySelector('.cv-form');
        if (!form) return;

        // Set enctype for file upload
        form.setAttribute('enctype', 'multipart/form-data');

        // Create hidden file input inside form
        const existingHidden = form.querySelector('input[name="cv_file"]');
        if (existingHidden) existingHidden.remove();

        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.name = 'cv_file';
        fileInput.style.display = 'none';

        // Copy the file to the new input via DataTransfer
        const dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;

        form.appendChild(fileInput);
        form.submit();

        this.value = '';
    });
}
