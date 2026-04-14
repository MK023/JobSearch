/**
 * Alpine component for AI preferences toggle in /settings.
 * Reads from GET /api/preferences/<key>, writes via PUT.
 */

function aiPreferences() {
    var KEY = 'ai_sonnet_fallback_on_low_confidence';

    return {
        sonnetFallback: false,
        loading: false,
        message: '',

        load: function() {
            var self = this;
            fetch('/api/preferences/' + KEY)
                .then(function(r) {
                    if (!r.ok) throw new Error('load failed: ' + r.status);
                    return r.json();
                })
                .then(function(data) { self.sonnetFallback = !!data.value; })
                .catch(function(e) { self.message = 'Errore lettura: ' + e.message; });
        },

        save: function() {
            var self = this;
            self.loading = true;
            self.message = '';
            fetch('/api/preferences/' + KEY, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value: self.sonnetFallback })
            })
                .then(function(r) {
                    if (!r.ok) throw new Error('save failed: ' + r.status);
                    return r.json();
                })
                .then(function() { self.message = 'Salvato'; })
                .catch(function(e) {
                    self.message = 'Errore salvataggio: ' + e.message;
                })
                .finally(function() { self.loading = false; });
        }
    };
}
