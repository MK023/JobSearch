/**
 * Agenda to-do — server-side persistence via /api/v1/todos.
 *
 * Tutte le mutation usano `window.fetchJSON` (vedi app.js): r.ok check
 * automatico, .catch riceve Error con status code per toast specifici.
 */

function _todoErrorMessage(e) {
    if (e && e.status) {
        if (e.status >= 500) return 'Errore server (HTTP ' + e.status + ')';
        if (e.status === 401) return 'Sessione scaduta';
        return 'Errore richiesta (HTTP ' + e.status + ')';
    }
    return 'Errore di rete';
}

function addTodoServer() {
    const input = document.getElementById('agenda-todo-input');
    const text = (input.value || '').trim();
    if (!text) return;

    const fd = new FormData();
    fd.append('text', text);

    fetchJSON('/api/v1/todos', { method: 'POST', body: fd })
        .then(function (data) {
            if (data.ok) {
                input.value = '';
                globalThis.location.reload();
            } else {
                showToast(data.error || 'Errore', 'error');
            }
        })
        .catch(function (e) {
            console.error('addTodo error:', e);
            showToast(_todoErrorMessage(e), 'error');
        });
}

function toggleTodo(id) {
    fetchJSON('/api/v1/todos/' + id + '/toggle', { method: 'POST' })
        .then(function (data) {
            if (data.ok) globalThis.location.reload();
        })
        .catch(function (e) {
            console.error('toggleTodo error:', e);
            showToast(_todoErrorMessage(e), 'error');
        });
}

function removeTodo(id) {
    fetchJSON('/api/v1/todos/' + id, { method: 'DELETE' })
        .then(function (data) {
            if (data.ok) globalThis.location.reload();
        })
        .catch(function (e) {
            console.error('removeTodo error:', e);
            showToast(_todoErrorMessage(e), 'error');
        });
}
