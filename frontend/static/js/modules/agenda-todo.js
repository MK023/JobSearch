/**
 * Agenda to-do — server-side persistence via /api/v1/todos.
 */

function addTodoServer() {
    const input = document.getElementById('agenda-todo-input');
    const text = (input.value || '').trim();
    if (!text) return;

    const fd = new FormData();
    fd.append('text', text);

    fetch('/api/v1/todos', { method: 'POST', body: fd })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.ok) {
                input.value = '';
                globalThis.location.reload();
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
            if (data.ok) globalThis.location.reload();
        })
        .catch(function () { showToast('Errore', 'error'); });
}

function removeTodo(id) {
    fetch('/api/v1/todos/' + id, { method: 'DELETE' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.ok) globalThis.location.reload();
        })
        .catch(function () { showToast('Errore', 'error'); });
}
