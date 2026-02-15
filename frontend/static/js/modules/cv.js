/**
 * CV file upload handler.
 */

function uploadCV() {
    document.getElementById('cv-file').click();
}

function initCVUpload() {
    var cvFile = document.getElementById('cv-file');
    if (!cvFile) return;

    cvFile.addEventListener('change', function() {
        var file = this.files[0];
        if (!file) return;

        var reader = new FileReader();
        reader.onload = function(e) {
            document.getElementById('cv-text').value = e.target.result;
        };
        reader.readAsText(file);
        this.value = '';
    });
}
