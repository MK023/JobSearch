/**
 * CV file upload handler.
 * Uploads the file directly to the backend for server-side text extraction.
 */

var CV_ALLOWED_EXT = ['.txt', '.pdf', '.doc', '.docx'];
var CV_MAX_SIZE = 10 * 1024 * 1024; // 10 MB

function uploadCV() {
    document.getElementById('cv-file').click();
}

function initCVUpload() {
    var cvFile = document.getElementById('cv-file');
    if (!cvFile) return;

    cvFile.addEventListener('change', function() {
        var file = this.files[0];
        if (!file) return;

        // Validate extension
        var ext = '.' + file.name.split('.').pop().toLowerCase();
        if (CV_ALLOWED_EXT.indexOf(ext) === -1) {
            showToast('Formato non supportato. Usa PDF, DOCX, DOC o TXT.', 'error');
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
        var form = document.querySelector('.cv-form');
        if (!form) return;

        // Set enctype for file upload
        form.setAttribute('enctype', 'multipart/form-data');

        // Create hidden file input inside form
        var existingHidden = form.querySelector('input[name="cv_file"]');
        if (existingHidden) existingHidden.remove();

        var fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.name = 'cv_file';
        fileInput.style.display = 'none';

        // Copy the file to the new input via DataTransfer
        var dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;

        form.appendChild(fileInput);
        form.submit();

        this.value = '';
    });
}
