"""Tests for the /health endpoint."""

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.main import create_app


@pytest.fixture
def client():
    @asynccontextmanager
    async def _test_lifespan(app):
        from src.integrations.cache import NullCacheService

        app.state.cache = NullCacheService()
        yield

    with patch("src.main.lifespan", _test_lifespan), patch("src.main.settings") as mock_settings:
        mock_settings.trusted_hosts_list = ["*"]
        mock_settings.cors_origins_list = ["*"]
        mock_settings.cors_allow_credentials = True
        mock_settings.secret_key = "test-secret"  # noqa: S105
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestHealthEndpoint:
    def test_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_minimal_payload_when_unauthenticated(self, client):
        """Unauthenticated health check returns only status (no system info leak)."""
        r = client.get("/health").json()
        assert r["status"] in ("ok", "degraded")
        assert "db" not in r
        assert "version" not in r
        assert "uptime_seconds" not in r


@pytest.fixture
def logged_in_client(db_session, test_user):
    """TestClient con una sessione VERA, ottenuta via POST /login.

    `/health` legge `request.session["user_id"]` direttamente, non passa da
    `get_current_user`: sovrascrivere quella dipendenza (come fa
    test_batch_routes) qui non servirebbe a niente. Serve il cookie di
    sessione firmato, e l'unico modo onesto di averlo è fare il login.
    """
    from src.auth.service import hash_password
    from src.database import get_db
    from src.main import create_app

    test_user.password_hash = hash_password("hunter2-test")
    db_session.commit()

    @asynccontextmanager
    async def _test_lifespan(app):
        from src.integrations.cache import NullCacheService

        app.state.cache = NullCacheService()
        yield

    def _db():
        yield db_session

    with patch("src.main.lifespan", _test_lifespan), patch("src.main.settings") as s:
        s.trusted_hosts_list = ["*"]
        # `create_app` calcola https_only da `settings.trusted_hosts` (stringa,
        # non la lista). Su un MagicMock `"localhost" not in <mock>` è True →
        # https_only=True → il cookie di sessione non viaggia su http://testserver
        # e il login "riesce" ma la sessione sparisce. Va impostato esplicito.
        s.trusted_hosts = "localhost,testserver"
        s.cors_origins_list = ["*"]
        s.cors_allow_credentials = True
        s.secret_key = "test-secret"  # noqa: S105
        s.rate_limit_default = "100/minute"
        app = create_app()
        app.dependency_overrides[get_db] = _db
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post(
                "/login",
                data={"email": test_user.email, "password": "hunter2-test"},
                follow_redirects=False,
            )
            assert r.status_code == 303, f"login fallito: {r.status_code} — la fixture è rotta"
            yield c


class TestHealthReportsRunningCommit:
    """`/health` deve dire QUALE commit sta girando, non una versione hardcoded.

    Il 16/07/2026 la produzione ha servito il container del 22 giugno per
    un'ora dopo un merge: il deploy era fallito e Render aveva (giustamente)
    tenuto vivo il vecchio. Dall'esterno era indistinguibile da un'app sana —
    e anche i 6 check Checkly su /health sono rimasti verdi tutto il tempo,
    perché un 200 non dice *quale codice* ha risposto.

    `version` era hardcoded a "2.0.0": lo stesso identico valore nel container
    nuovo e in quello vecchio. Un campo che non cambia col deploy non è
    un'informazione, è un'etichetta.

    RENDER_GIT_COMMIT è popolata da Render a runtime:
    https://render.com/docs/environment-variables
    """

    def test_riporta_il_commit_quando_autenticato(self, logged_in_client, monkeypatch):
        monkeypatch.setenv("RENDER_GIT_COMMIT", "abc1234def5678901234")
        r = logged_in_client.get("/health").json()
        assert r.get("commit") == "abc1234", (
            f"deve riportare il commit corto del container in esecuzione, trovato: {r.get('commit')!r}"
        )

    def test_commit_none_fuori_da_render(self, logged_in_client, monkeypatch):
        """In locale la variabile non c'è: si dichiara None, non si finge."""
        monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
        r = logged_in_client.get("/health").json()
        assert r.get("commit") is None

    def test_il_commit_non_trapela_agli_anonimi(self, client, monkeypatch):
        """Il confine di sicurezza già esistente resta intatto."""
        monkeypatch.setenv("RENDER_GIT_COMMIT", "abc1234def5678901234")
        r = client.get("/health").json()
        assert set(r.keys()) == {"status"}, f"anonimo deve vedere solo status, non {sorted(r.keys())}"
