/**
 * Spending bar: budget editing and live refresh.
 */

function initBudgetEditing() {
    const budgetEl = document.getElementById('spending-budget');
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
    const budgetEl = document.getElementById('spending-budget');
    if (!budgetEl) return;

    const raw = budgetEl.textContent.replaceAll(/[^0-9.,]/g, '').replace(',', '.');
    let val = Number.parseFloat(raw);
    if (Number.isNaN(val) || val < 0) val = 0;
    budgetEl.textContent = '$' + val.toFixed(2);

    const fd = new FormData();
    fd.append('budget', val);
    fetch('/api/v1/spending/budget', { method: 'PUT', body: fd })
        .then(function() { refreshSpending(); })
        .catch(function(e) { console.error('saveBudget error:', e); });
}

function _remainingClass(remaining) {
    if (remaining < 1) return 'credit-remaining-low';
    if (remaining < 3) return 'credit-remaining-warn';
    return 'credit-remaining-ok';
}

function refreshSpending() {
    fetch('/api/v1/spending')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            const costEl = document.getElementById('spending-cost');
            if (!costEl) return;

            costEl.textContent = '$' + d.total_cost_usd.toFixed(4);

            const budgetDisplay = document.getElementById('spending-budget');
            if (budgetDisplay && !budgetDisplay.matches(':focus')) {
                budgetDisplay.textContent = '$' + d.budget.toFixed(2);
            }

            const remainEl = document.getElementById('spending-remaining');
            if (remainEl) {
                remainEl.classList.remove('credit-remaining-low', 'credit-remaining-warn', 'credit-remaining-ok');
                if (d.remaining === null) {
                    remainEl.textContent = '-';
                } else {
                    remainEl.textContent = '$' + d.remaining.toFixed(4);
                    remainEl.classList.add(_remainingClass(d.remaining));
                }
            }

            const todayEl = document.getElementById('spending-today');
            if (todayEl) {
                const todayTok = d.today_tokens_input + d.today_tokens_output;
                todayEl.textContent = '$' + d.today_cost_usd.toFixed(4) +
                    ' (' + d.today_analyses + ' analisi, ' + todayTok.toLocaleString('it-IT') + ' tok)';
            }
        })
        .catch(function(e) { console.error('refreshSpending error:', e); });
}
