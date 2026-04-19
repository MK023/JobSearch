/**
 * Alpine component for AI preferences toggle in /settings.
 * Reads from GET /api/preferences/<key>, writes via PUT.
 */

function aiPreferences() {
    const KEY = 'ai_sonnet_fallback_on_low_confidence';

    return {
        sonnetFallback: false,
        loading: false,
        message: '',

        load: function() {
            fetch('/api/preferences/' + KEY)
                .then(function(r) {
                    if (!r.ok) throw new Error('load failed: ' + r.status);
                    return r.json();
                })
                .then((data) => { this.sonnetFallback = !!data.value; })
                .catch((e) => { this.message = 'Errore lettura: ' + e.message; });
        },

        save: function() {
            this.loading = true;
            this.message = '';
            fetch('/api/preferences/' + KEY, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value: this.sonnetFallback })
            })
                .then(function(r) {
                    if (!r.ok) throw new Error('save failed: ' + r.status);
                    return r.json();
                })
                .then(() => { this.message = 'Salvato'; })
                .catch((e) => {
                    this.message = 'Errore salvataggio: ' + e.message;
                })
                .finally(() => { this.loading = false; });
        }
    };
}
