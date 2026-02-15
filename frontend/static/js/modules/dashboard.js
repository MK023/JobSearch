/**
 * Dashboard: live refresh of stats and motivation.
 */

function refreshDashboard() {
    fetch('/api/v1/dashboard')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var dash = document.getElementById('dashboard-details');
            if (!dash) return;

            if (d.total > 0) {
                dash.style.display = '';
            } else {
                dash.style.display = 'none';
                return;
            }

            var el = function(id) { return document.getElementById(id); };

            el('dashboard-total').textContent = d.total;
            el('dashboard-applied').textContent = d.applied;
            el('dashboard-interviews').textContent = d.interviews;
            el('dashboard-avg').textContent = d.avg_score;
            el('dashboard-skipped').textContent = d.skipped;

            var fuBox = el('dashboard-followup-box');
            if (fuBox) {
                if (d.followup_count > 0) {
                    fuBox.style.display = '';
                    el('dashboard-followup').textContent = d.followup_count;
                } else {
                    fuBox.style.display = 'none';
                }
            }

            el('dashboard-summary-stats').textContent =
                d.total + ' analisi \u00b7 ' + d.applied + ' candidature \u00b7 score medio ' + d.avg_score;

            var mot = el('dashboard-motivation');
            if (mot) {
                if (d.top_match) {
                    while (mot.firstChild) mot.removeChild(mot.firstChild);
                    mot.appendChild(document.createTextNode('\uD83C\uDFC6 Miglior match: '));
                    var b = document.createElement('b');
                    b.textContent = d.top_match.role;
                    mot.appendChild(b);
                    var suffix = ' @ ' + d.top_match.company + ' (' + d.top_match.score + '/100)';
                    if (d.applied > 0) {
                        suffix += ' \u00b7 Hai gia\' inviato ' + d.applied +
                            ' candidatur' + (d.applied === 1 ? 'a' : 'e') + ' - continua cosi\'!';
                    }
                    mot.appendChild(document.createTextNode(suffix));
                    mot.style.display = '';
                } else {
                    mot.style.display = 'none';
                }
            }
        })
        .catch(function(e) { console.error('refreshDashboard error:', e); });
}
