"""Tag outbound exceptions with the ingestion source.

Marco's directive: "le notifiche sono come microservizi indipendenti
per fonte, e la stessa cosa vale per la gestione degli errori."

Sentry groups issues by stack + tags. Without a `flow_source` tag,
a failure in the Chrome-extension pipeline and a failure in the
cowork form submit would land in the same issue bucket and we'd
have no way to tell which channel is degrading. With the tag, the
dashboard splits by flow and alerts can be routed per source.

Two entry points:

* HTTP routes — the middleware infers the source from the request
  path (fast, zero per-handler annotation).
* Background tasks / CLI scripts — call :func:`tag_flow_source`
  explicitly before the risky code path (middleware doesn't see
  them).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Path -> source mapping. Keep this as a tuple-of-tuples (prefix, source)
# matched in order; the first hit wins. Ordered specific-first so
# `/api/v1/inbox` beats the generic `/api/v1` fallback.
_PATH_PREFIX_TO_SOURCE: tuple[tuple[str, str], ...] = (
    ("/api/v1/inbox", "extension"),
    ("/api/v1/analysis/import", "mcp"),
    ("/api/v1/analyze", "api"),
    ("/analyze", "cowork"),
)


def infer_source_from_path(path: str) -> str | None:
    """Return the ``AnalysisSource`` value implied by ``path``, or None.

    Paths outside the analysis ingestion flows (/health, /dashboard, ...)
    return None — they aren't "analysis work" and shouldn't be tagged
    with a flow source they have nothing to do with.
    """
    if not path:
        return None
    for prefix, source in _PATH_PREFIX_TO_SOURCE:
        if path.startswith(prefix):
            return source
    return None


def tag_flow_source(source: str | None) -> None:
    """Attach ``source`` as the ``flow_source`` tag on the current Sentry
    scope. No-op when Sentry SDK is absent or ``source`` is None.

    Safe to call unconditionally — the sentry_sdk import is guarded so
    tests and local dev without the DSN configured pay nothing.
    """
    if not source:
        return
    try:
        import sentry_sdk  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]
    except ImportError:
        return
    # set_tag on the current scope is request-local once Sentry's FastAPI
    # integration is installed — each request carries its own scope so
    # tags don't leak across concurrent flows.
    sentry_sdk.set_tag("flow_source", source)
