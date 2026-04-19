/**
 * Stats page — Chart.js wiring.
 *
 * Legge il payload statico da <script id="stats-payload" type="application/json">
 * (zero fetch, zero race condition, zero cache invalidation).
 * Ogni chart usa palette CSS-var-driven così segue il tema chiaro/scuro.
 */

(function () {
    'use strict';

    function readPayload() {
        const el = document.getElementById('stats-payload');
        if (!el) return null;
        try { return JSON.parse(el.textContent); } catch (e) {
            // Malformed SSR payload — render-time bug on the server. Log for
            // visibility but don't throw: the page degrades to "no charts".
            console.debug('stats-payload JSON parse failed:', e);
            return null;
        }
    }

    function themeColor(varName, fallback) {
        const v = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
        return v || fallback;
    }

    const PALETTE = [
        '#0ea5e9', '#10b981', '#f59e0b', '#ef4444',
        '#8b5cf6', '#ec4899', '#14b8a6', '#f97316',
        '#6366f1', '#84cc16'
    ];

    function baseOptions(opts) {
        const fg = themeColor('--text-primary', '#c9d1d9');
        const muted = themeColor('--text-secondary', '#8b949e');
        const grid = themeColor('--border-subtle', 'rgba(255,255,255,0.1)');
        const isDoughnut = opts?.noScales;
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: isDoughnut ? {
                    position: 'bottom',
                    labels: {
                        color: fg,
                        font: { size: 11, weight: 600 },
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 14
                    }
                } : {
                    display: false
                },
                tooltip: {
                    backgroundColor: themeColor('--bg-tertiary', '#161b22'),
                    titleColor: fg,
                    bodyColor: fg,
                    borderColor: grid,
                    borderWidth: 1,
                    padding: 10,
                    cornerRadius: 8,
                    displayColors: true,
                    boxPadding: 4
                }
            },
            scales: isDoughnut ? {} : {
                x: { ticks: { color: muted, font: { size: 11 } }, grid: { color: grid } },
                y: { ticks: { color: muted, font: { size: 11 } }, grid: { color: grid }, beginAtZero: true }
            }
        };
    }

    function renderFunnel(data) {
        const ctx = document.getElementById('chart-funnel');
        if (!ctx || !data) return;
        const labels = ['da_valutare', 'candidato', 'colloquio', 'offerta', 'scartato'];
        const colors = ['#6b7280', '#0ea5e9', '#10b981', '#a855f7', '#ef4444'];
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Analisi per stato',
                    data: labels.map(function (l) { return data[l] || 0; }),
                    backgroundColor: colors,
                    borderWidth: 0
                }]
            },
            options: baseOptions()
        });
    }

    function renderScoreDistribution(items) {
        const ctx = document.getElementById('chart-score-distribution');
        if (!ctx || !items) return;
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: items.map(function (x) { return x.bin; }),
                datasets: [{
                    label: 'Candidature',
                    data: items.map(function (x) { return x.count; }),
                    backgroundColor: ['#ef4444', '#f59e0b', '#eab308', '#10b981', '#0ea5e9'],
                    borderWidth: 0
                }]
            },
            options: baseOptions()
        });
    }

    function renderApplicationsPerWeek(items) {
        const ctx = document.getElementById('chart-applications-per-week');
        if (!ctx || !items) return;
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: items.map(function (x) { return x.week; }),
                datasets: [{
                    label: 'Candidature',
                    data: items.map(function (x) { return x.count; }),
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.15)',
                    tension: 0.3,
                    fill: true,
                    pointRadius: 3
                }]
            },
            options: baseOptions()
        });
    }

    function renderTopCompanies(items) {
        const ctx = document.getElementById('chart-top-companies');
        if (!ctx || !items) return;
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: items.map(function (x) { return x.company; }),
                datasets: [{
                    label: 'Analisi',
                    data: items.map(function (x) { return x.count; }),
                    backgroundColor: PALETTE,
                    borderWidth: 0
                }]
            },
            options: { ...baseOptions(), indexAxis: 'y' }
        });
    }

    function renderWorkMode(items) {
        const ctx = document.getElementById('chart-work-mode');
        if (!ctx || !items) return;
        new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: items.map(function (x) { return x.mode; }),
                datasets: [{
                    data: items.map(function (x) { return x.count; }),
                    backgroundColor: PALETTE,
                    borderWidth: 0
                }]
            },
            options: baseOptions({ noScales: true })
        });
    }

    function renderContractSplit(data) {
        const ctx = document.getElementById('chart-contract-split');
        if (!ctx || !data) return;
        const labels = ['dipendente', 'body_rental', 'freelance', 'recruiter_esterno'];
        new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: labels.map(function (l) { return data[l] || 0; }),
                    backgroundColor: ['#10b981', '#f59e0b', '#ef4444', '#8b5cf6'],
                    borderWidth: 0
                }]
            },
            options: baseOptions({ noScales: true })
        });
    }

    function renderRecommendation(data) {
        const ctx = document.getElementById('chart-recommendation');
        if (!ctx || !data) return;
        new Chart(ctx, {
            type: 'pie',
            data: {
                labels: ['APPLY', 'CONSIDER', 'SKIP', 'ALTRO'],
                datasets: [{
                    data: [data.APPLY || 0, data.CONSIDER || 0, data.SKIP || 0, data.ALTRO || 0],
                    backgroundColor: ['#10b981', '#f59e0b', '#ef4444', '#6b7280'],
                    borderWidth: 0
                }]
            },
            options: baseOptions({ noScales: true })
        });
    }

    function renderScoreByStatus(items) {
        const ctx = document.getElementById('chart-score-by-status');
        if (!ctx || !items) return;
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: items.map(function (x) { return x.status; }),
                datasets: [{
                    label: 'Score medio',
                    data: items.map(function (x) { return x.avg_score; }),
                    backgroundColor: PALETTE,
                    borderWidth: 0
                }]
            },
            options: baseOptions()
        });
    }

    function renderSpending(items) {
        const ctx = document.getElementById('chart-spending');
        if (!ctx || !items) return;
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: items.map(function (x) { return x.day; }),
                datasets: [{
                    label: 'USD',
                    data: items.map(function (x) { return x.cost_usd; }),
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.15)',
                    tension: 0.25,
                    fill: true,
                    pointRadius: 2
                }]
            },
            options: baseOptions()
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        if (typeof Chart === 'undefined') return;
        const payload = readPayload();
        if (!payload) return;
        renderFunnel(payload.funnel);
        renderScoreDistribution(payload.score_distribution);
        renderApplicationsPerWeek(payload.applications_per_week);
        renderTopCompanies(payload.top_companies);
        renderWorkMode(payload.work_mode_split);
        renderContractSplit(payload.contract_split);
        renderRecommendation(payload.recommendation_split);
        renderScoreByStatus(payload.score_by_status);
        renderSpending(payload.spending_timeline);
    });
})();
