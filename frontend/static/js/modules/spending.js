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

    const raw = budgetEl.textContent.replace(/[^0-9.,]/g, '').replace(',', '.');
    let val = parseFloat(raw);
    if (isNaN(val) || val < 0) val = 0;
    budgetEl.textContent = '$' + val.toFixed(2);

    const fd = new FormData();
    fd.append('budget', val);
    fetch('/api/v1/spending/budget', { method: 'PUT', body: fd })
        .then(function() { refreshSpending(); })
        .catch(function(e) { console.error('saveBudget error:', e); });
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
                if (d.remaining !== null) {
                    remainEl.textContent = '$' + d.remaining.toFixed(4);
                    remainEl.classList.remove('credit-remaining-low', 'credit-remaining-warn', 'credit-remaining-ok');
                    remainEl.classList.add(d.remaining < 1 ? 'credit-remaining-low' : d.remaining < 3 ? 'credit-remaining-warn' : 'credit-remaining-ok');
                } else {
                    remainEl.textContent = '-';
                    remainEl.classList.remove('credit-remaining-low', 'credit-remaining-warn', 'credit-remaining-ok');
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
