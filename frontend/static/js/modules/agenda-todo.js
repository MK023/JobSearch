/**
 * Agenda to-do — server-side persistence via /api/v1/todos.
 */

function addTodoServer() {
    var input = document.getElementById('agenda-todo-input');
    var text = (input.value || '').trim();
    if (!text) return;

    var fd = new FormData();
    fd.append('text', text);

    fetch('/api/v1/todos', { method: 'POST', body: fd })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.ok) {
                input.value = '';
                window.location.reload();
            } else {
                showToast(data.error || 'Errore', 'error');
            }
        })
        .catch(function () { showToast('Errore di rete', 'error'); });
}

function toggleTodo(id) {
    fetch('/api/v1/todos/' + id + '/toggle', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.ok) window.location.reload();
        })
        .catch(function () { showToast('Errore', 'error'); });
}

function removeTodo(id) {
    fetch('/api/v1/todos/' + id, { method: 'DELETE' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.ok) window.location.reload();
        })
        .catch(function () { showToast('Errore', 'error'); });
}
