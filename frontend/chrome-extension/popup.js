/**
 * JobSearch Inbox — popup controller.
 *
 * Flow:
 *   1. On open, load endpoint + apiKey from chrome.storage.sync.
 *   2. User pastes (or clicks Auto-capture to inject into the active tab).
 *   3. Click Send → POST to {endpoint}/api/v1/inbox with X-API-Key header.
 *   4. Display inbox_id + dedup/pending status + link back to JobSearch.
 *
 * Zero framework, zero background worker — popup is the only surface.
 * Settings are panel-toggled, not a separate page. innerHTML is never used
 * with untrusted content — textContent/createElement everywhere to avoid
 * any XSS foothold (the status area hosts user-facing DOM nodes only).
 */

(function () {
    'use strict';

    const DEFAULT_ENDPOINT = 'https://www.jobsearches.cc';
    const MIN_TEXT = 50;
    const MAX_TEXT = 50_000;

    // Host → source auto-detection map (matches backend's whitelist).
    const HOST_TO_SOURCE = {
        'linkedin.com': 'linkedin',
        'indeed.com': 'indeed',
        'indeed.it': 'indeed',
        'infojobs.it': 'infojobs',
        'welcometothejungle.com': 'wttj',
        'remoteok.com': 'remote_ok',
        'remoteok.io': 'remote_ok',
    };

    const $ = (id) => document.getElementById(id);

    const els = {
        main: $('main-panel'),
        settings: $('settings-panel'),
        toggleSettings: $('toggle-settings'),
        source: $('source-select'),
        rawText: $('raw-text'),
        charCount: $('char-count'),
        captureBtn: $('capture-btn'),
        sendBtn: $('send-btn'),
        status: $('status'),
        endpointInput: $('endpoint-input'),
        apikeyInput: $('apikey-input'),
        toggleApikey: $('toggle-apikey'),
        saveSettings: $('save-settings'),
    };

    let state = {
        endpoint: DEFAULT_ENDPOINT,
        apiKey: '',
    };

    function clearNode(node) {
        // textContent = '' detaches all children without any HTML parsing.
        node.textContent = '';
    }

    function setStatus(message, kind) {
        els.status.className = 'status' + (kind ? ' status-' + kind : '');
        if (typeof message === 'string') {
            els.status.textContent = message;
        } else {
            clearNode(els.status);
            els.status.appendChild(message);
        }
    }

    function updateCharCount() {
        const n = els.rawText.value.length;
        els.charCount.textContent = `${n} caratter${n === 1 ? 'e' : 'i'}`;
        els.sendBtn.disabled = n < MIN_TEXT || n > MAX_TEXT || !state.apiKey;
    }

    // Endpoint is user-supplied via settings → must be validated against any
    // non-https scheme before it ever flows into fetch() or <a href>. We keep
    // only the origin (scheme + host + port), dropping paths/queries/fragments.
    function normalizeEndpoint(raw) {
        try {
            const url = new URL((raw || '').trim());
            if (url.protocol !== 'https:') return DEFAULT_ENDPOINT;
            return url.origin;
        } catch (_) {
            return DEFAULT_ENDPOINT;
        }
    }

    async function loadSettings() {
        return new Promise((resolve) => {
            chrome.storage.sync.get(['endpoint', 'apiKey'], (items) => {
                state.endpoint = normalizeEndpoint(items.endpoint);
                state.apiKey = items.apiKey || '';
                els.endpointInput.value = state.endpoint;
                els.apikeyInput.value = state.apiKey;
                resolve();
            });
        });
    }

    function saveSettings() {
        const endpoint = normalizeEndpoint(els.endpointInput.value);
        const apiKey = els.apikeyInput.value.trim();
        chrome.storage.sync.set({ endpoint, apiKey }, () => {
            state.endpoint = endpoint;
            state.apiKey = apiKey;
            els.endpointInput.value = endpoint;
            setStatus('Impostazioni salvate.', 'success');
            updateCharCount();
            toggleSettings(false);
        });
    }

    function toggleSettings(show) {
        const willShow = typeof show === 'boolean' ? show : els.settings.classList.contains('hidden');
        els.settings.classList.toggle('hidden', !willShow);
        els.main.classList.toggle('hidden', willShow);
        els.settings.setAttribute('aria-hidden', String(!willShow));
    }

    function autoDetectSource(url) {
        try {
            const host = new URL(url).hostname.toLowerCase();
            for (const [suffix, source] of Object.entries(HOST_TO_SOURCE)) {
                if (host === suffix || host.endsWith('.' + suffix)) return source;
            }
        } catch (_) {
            // malformed URL — leave as manual
        }
        return 'manual';
    }

    async function getActiveTab() {
        return new Promise((resolve) => {
            chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => resolve(tabs[0] || null));
        });
    }

    async function autoCapture() {
        const tab = await getActiveTab();
        if (!tab || !tab.id) {
            setStatus('Nessuna tab attiva da leggere.', 'error');
            return;
        }

        setStatus('Lettura pagina…');
        try {
            const [{ result }] = await chrome.scripting.executeScript({
                target: { tabId: tab.id },
                func: () => document.body ? document.body.innerText.trim() : '',
            });
            if (!result || result.length < MIN_TEXT) {
                setStatus('Pagina troppo corta o non accessibile. Incolla manualmente.', 'error');
                return;
            }
            els.rawText.value = result.slice(0, MAX_TEXT);
            els.source.value = autoDetectSource(tab.url || '');
            updateCharCount();
            setStatus(`Catturati ${result.length} caratteri. Rivedi e invia.`, 'success');
        } catch (e) {
            setStatus('Impossibile leggere questa pagina (permessi o errore script).', 'error');
        }
    }

    // Build the link to the analysis or history using the URL constructor so
    // the result is always rooted at state.endpoint (already validated https).
    // Direct string concatenation would let a crafted endpoint produce e.g.
    // "javascript:..." hrefs — URL() + https-only normalization prevents that.
    function buildAnalysisUrl(analysisId) {
        const path = analysisId ? `/analysis/${encodeURIComponent(analysisId)}` : '/history';
        try {
            const url = new URL(path, state.endpoint);
            if (url.protocol !== 'https:') return null;
            return url.toString();
        } catch (_) {
            return null;
        }
    }

    function buildSuccessStatus(data) {
        const span = document.createElement('span');
        const verb = data.dedup ? 'Già in archivio' : 'Analisi avviata';
        span.appendChild(document.createTextNode(`${verb}. `));

        const href = buildAnalysisUrl(data.analysis_id);
        if (href) {
            const link = document.createElement('a');
            link.textContent = data.analysis_id ? 'Apri analisi →' : 'Apri storico →';
            link.href = href;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            span.appendChild(link);
        }
        return span;
    }

    async function send() {
        const rawText = els.rawText.value;
        if (rawText.length < MIN_TEXT) {
            setStatus(`Testo troppo corto (min ${MIN_TEXT}).`, 'error');
            return;
        }
        if (!state.apiKey) {
            setStatus('API Key mancante — apri Impostazioni.', 'error');
            toggleSettings(true);
            return;
        }

        const tab = await getActiveTab();
        const sourceUrl = (tab && tab.url && /^https?:/.test(tab.url)) ? tab.url : state.endpoint;

        const payload = {
            raw_text: rawText,
            source_url: sourceUrl,
            source: els.source.value,
        };

        els.sendBtn.disabled = true;
        setStatus('Invio in corso…');

        try {
            const res = await fetch(`${state.endpoint}/api/v1/inbox`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-API-Key': state.apiKey,
                    Accept: 'application/json',
                },
                body: JSON.stringify(payload),
            });

            if (!res.ok) {
                const errBody = await res.json().catch(() => ({}));
                const raw = errBody.error || errBody.detail;
                const msg = typeof raw === 'string' ? raw : (raw ? JSON.stringify(raw).slice(0, 120) : `HTTP ${res.status}`);
                setStatus(`Errore: ${msg}`, 'error');
                els.sendBtn.disabled = false;
                return;
            }

            const data = await res.json();
            setStatus(buildSuccessStatus(data), 'success');
            els.rawText.value = '';
            updateCharCount();
        } catch (e) {
            setStatus(`Errore di rete: ${e.message || 'impossibile raggiungere il server'}.`, 'error');
            els.sendBtn.disabled = false;
        }
    }

    // --- Wiring ---

    els.toggleSettings.addEventListener('click', () => toggleSettings());
    els.saveSettings.addEventListener('click', saveSettings);
    els.captureBtn.addEventListener('click', autoCapture);
    els.sendBtn.addEventListener('click', send);
    els.rawText.addEventListener('input', updateCharCount);

    els.toggleApikey.addEventListener('click', () => {
        const current = els.apikeyInput.type;
        els.apikeyInput.type = current === 'password' ? 'text' : 'password';
    });

    // Keyboard: Ctrl/Cmd+Enter sends; Esc closes settings.
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !els.sendBtn.disabled) {
            send();
        }
        if (e.key === 'Escape' && !els.settings.classList.contains('hidden')) {
            toggleSettings(false);
        }
    });

    // Init
    loadSettings().then(() => {
        updateCharCount();
        if (!state.apiKey) {
            setStatus('Benvenuto. Configura la API key nelle Impostazioni per iniziare.');
            toggleSettings(true);
        } else {
            getActiveTab().then((tab) => {
                if (tab && tab.url) els.source.value = autoDetectSource(tab.url);
            });
        }
    });
})();
