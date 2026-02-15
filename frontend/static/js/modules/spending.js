/**
 * Spending bar: budget editing and live refresh.
 */

function initBudgetEditing() {
    var budgetEl = document.getElementById('spending-budget');
    if (!budgetEl) return;

    budgetEl.addEventListener('blur', saveBudget);
    budgetEl.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            budgetEl.blur();
        }
    });
}

function saveBudget() {
    var budgetEl = document.getElementById('spending-budget');
    if (!budgetEl) return;

    var raw = budgetEl.textContent.replace(/[^0-9.,]/g, '').replace(',', '.');
    var val = parseFloat(raw);
    if (isNaN(val) || val < 0) val = 0;
    budgetEl.textContent = '$' + val.toFixed(2);

    var fd = new FormData();
    fd.append('budget', val);
    fetch('/api/v1/spending/budget', { method: 'PUT', body: fd })
        .then(function() { refreshSpending(); })
        .catch(function(e) { console.error('saveBudget error:', e); });
}

function refreshSpending() {
    fetch('/api/v1/spending')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var costEl = document.getElementById('spending-cost');
            if (!costEl) return;

            costEl.textContent = '$' + d.total_cost_usd.toFixed(4);

            var budgetDisplay = document.getElementById('spending-budget');
            if (budgetDisplay && !budgetDisplay.matches(':focus')) {
                budgetDisplay.textContent = '$' + d.budget.toFixed(2);
            }

            var remainEl = document.getElementById('spending-remaining');
            if (remainEl) {
                if (d.remaining !== null) {
                    remainEl.textContent = '$' + d.remaining.toFixed(4);
                    remainEl.style.color = d.remaining < 1 ? '#f87171' : d.remaining < 3 ? '#fbbf24' : '#34d399';
                } else {
                    remainEl.textContent = '-';
                }
            }

            var todayEl = document.getElementById('spending-today');
            if (todayEl) {
                var todayTok = d.today_tokens_input + d.today_tokens_output;
                todayEl.textContent = '$' + d.today_cost_usd.toFixed(4) +
                    ' (' + d.today_analyses + ' analisi, ' + todayTok.toLocaleString('it-IT') + ' tok)';
            }
        })
        .catch(function(e) { console.error('refreshSpending error:', e); });
}
