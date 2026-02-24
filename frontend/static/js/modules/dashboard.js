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
            refreshUpcomingBanners();
        })
        .catch(function(e) { console.error('refreshDashboard error:', e); });
}

function refreshUpcomingBanners() {
    fetch('/api/v1/interviews-upcoming')
        .then(function(r) { return r.json(); })
        .then(function(interviews) {
            // Remove old banners
            document.querySelectorAll('.upcoming-interview-banner').forEach(function(el) {
                el.remove();
            });

            if (!interviews.length) return;

            // Find insertion point (before dashboard-details)
            var dashboard = document.getElementById('dashboard-details');
            if (!dashboard) return;

            interviews.forEach(function(iv) {
                var banner = document.createElement('div');
                banner.className = 'upcoming-interview-banner';

                var info = document.createElement('div');
                info.className = 'upcoming-interview-info';

                var title = document.createElement('div');
                title.className = 'upcoming-interview-title';
                title.textContent = 'Colloquio in arrivo \u2014 ' + iv.company;
                info.appendChild(title);

                var meta = document.createElement('div');
                meta.className = 'upcoming-interview-meta';
                var dateStr = iv.scheduled_at.substring(0, 16).replace('T', ' ');
                var metaText = iv.role + ' \u00b7 ' + dateStr;
                if (iv.interview_type === 'virtual') metaText += ' \u00b7 Video call';
                else if (iv.interview_type === 'phone') metaText += ' \u00b7 Telefonico';
                else if (iv.interview_type === 'in_person') metaText += ' \u00b7 In presenza';
                meta.textContent = metaText;
                info.appendChild(meta);

                banner.appendChild(info);

                var link = document.createElement('a');
                link.href = '/analysis/' + encodeURIComponent(iv.analysis_id);
                link.className = 'btn btn-sm btn-primary';
                link.textContent = 'Apri dettaglio';
                banner.appendChild(link);

                dashboard.parentNode.insertBefore(banner, dashboard);
            });
        })
        .catch(function(e) { console.error('refreshUpcomingBanners error:', e); });
}
