/**
 * Dashboard: live refresh of upcoming interview banners.
 *
 * In the multi-page architecture, metric cards are server-rendered.
 * This module handles dynamic banner refresh for upcoming interviews.
 */

function refreshDashboard() {
    // Refresh upcoming interview banners on the dashboard page
    refreshUpcomingBanners();
}

function refreshUpcomingBanners() {
    // Only run on dashboard page
    var grid = document.querySelector('.grid-3col');
    if (!grid) return;

    fetch('/api/v1/interviews-upcoming')
        .then(function(r) { return r.json(); })
        .then(function(interviews) {
            // Remove old dynamic banners
            document.querySelectorAll('.upcoming-interview-banner.dynamic').forEach(function(el) {
                el.remove();
            });

            if (!interviews.length) return;

            // Find insertion point (after the grid)
            var insertPoint = grid.nextElementSibling;
            var parent = grid.parentNode;

            interviews.forEach(function(iv) {
                var banner = document.createElement('div');
                banner.className = 'upcoming-interview-banner dynamic';

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

                if (insertPoint) {
                    parent.insertBefore(banner, insertPoint);
                } else {
                    parent.appendChild(banner);
                }
            });
        })
        .catch(function(e) { console.error('refreshUpcomingBanners error:', e); });
}
