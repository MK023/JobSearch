"""Test per il client Arbeitnow — completamente offline, nessuna chiamata HTTP reale.

Si usa ``httpx.MockTransport`` per intercettare le richieste e restituire
risposte canned. Si verifica:
- normalizzazione (shape canonico WorldWild)
- paginazione fino a ``max_pages``
- early-stop su ``meta.last_page``
- filtro client-side ``remote_only``
- conversione Unix timestamp → datetime UTC
- normalizzazione ``job_types`` (``full-time`` → ``full_time``)
- graceful empty list su errori HTTP (no raise)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import httpx

from src.integrations import arbeitnow


def _job(
    slug: str = "abc-123",
    *,
    remote: bool = True,
    title: str = "Senior DevOps Engineer",
    company: str = "TestCorp",
    location: str = "Berlin, Germany",
    job_types: list[str] | None = None,
    created_at: int = 1717689600,  # 2024-06-06 16:00:00 UTC
) -> dict[str, Any]:
    return {
        "slug": slug,
        "company_name": company,
        "title": title,
        "description": "<p>Full remote, Kubernetes + AWS.</p>",
        "remote": remote,
        "url": f"https://www.arbeitnow.com/jobs/companies/testcorp/{slug}",
        "tags": ["devops", "kubernetes"],
        "job_types": job_types if job_types is not None else ["full-time"],
        "location": location,
        "created_at": created_at,
    }


def _page_payload(
    jobs: list[dict[str, Any]],
    *,
    current_page: int = 1,
    last_page: int = 1,
) -> dict[str, Any]:
    return {
        "data": jobs,
        "links": {"next": None, "prev": None},
        "meta": {
            "current_page": current_page,
            "last_page": last_page,
            "total": len(jobs),
        },
    }


def _make_transport(pages: list[dict[str, Any]]) -> httpx.MockTransport:
    """Costruisce un MockTransport che ritorna ``pages[i]`` alla i-esima GET.

    Se vengono fatte più richieste di quante pagine fornite, l'eccedenza
    riceve l'ultima pagina (caso difensivo: i test dovrebbero comunque
    fermarsi prima per via di ``last_page`` o ``max_pages``).
    """
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = min(state["i"], len(pages) - 1)
        state["i"] += 1
        return httpx.Response(200, json=pages[idx])

    return httpx.MockTransport(handler)


def _patch_client(transport: httpx.MockTransport) -> Any:
    """Patcha ``httpx.Client`` per usare il MockTransport ignorando ``timeout``.

    Serve perché ``fetch_arbeitnow_jobs`` istanzia ``httpx.Client(timeout=...)``
    e dobbiamo iniettare il transport senza modificare la firma del client.
    """
    real_client_cls = httpx.Client

    def _factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs.pop("timeout", None)
        return real_client_cls(transport=transport)

    return patch("src.integrations.arbeitnow.httpx.Client", side_effect=_factory)


class TestFetchArbeitnowJobs:
    def test_fetch_arbeitnow_basic_normalization(self) -> None:
        """Mock 1 pagina con 2 job → schema canonico corretto."""
        pages = [
            _page_payload(
                [_job("slug-a"), _job("slug-b", title="Platform Engineer")],
                current_page=1,
                last_page=1,
            )
        ]
        transport = _make_transport(pages)
        with _patch_client(transport):
            result = arbeitnow.fetch_arbeitnow_jobs(max_pages=3)

        assert len(result) == 2
        first = result[0]
        assert first["source"] == "arbeitnow"
        assert first["external_id"] == "slug-a"
        assert first["title"] == "Senior DevOps Engineer"
        assert first["company"] == "TestCorp"
        assert first["location"] == "Berlin, Germany"
        assert first["url"].endswith("/slug-a")
        assert first["description"].startswith("<p>")
        assert first["salary_min"] is None
        assert first["salary_max"] is None
        assert first["salary_currency"] == ""
        assert first["category"] == ""
        assert first["contract_type"] == "full_time"
        assert first["raw_payload"]["slug"] == "slug-a"
        assert isinstance(first["posted_at"], datetime)

    def test_fetch_arbeitnow_paginates_until_max_pages(self) -> None:
        """3 pagine disponibili, ``max_pages=3`` → fetch tutte e 3."""
        pages = [
            _page_payload([_job(f"p1-{i}") for i in range(2)], current_page=1, last_page=10),
            _page_payload([_job(f"p2-{i}") for i in range(2)], current_page=2, last_page=10),
            _page_payload([_job(f"p3-{i}") for i in range(2)], current_page=3, last_page=10),
        ]
        transport = _make_transport(pages)
        with _patch_client(transport):
            result = arbeitnow.fetch_arbeitnow_jobs(max_pages=3)

        assert len(result) == 6
        ext_ids = {r["external_id"] for r in result}
        assert ext_ids == {"p1-0", "p1-1", "p2-0", "p2-1", "p3-0", "p3-1"}

    def test_fetch_arbeitnow_stops_at_last_page(self) -> None:
        """``meta.last_page=2`` con ``max_pages=5`` → ferma a pagina 2."""
        pages = [
            _page_payload([_job("p1-a")], current_page=1, last_page=2),
            _page_payload([_job("p2-a")], current_page=2, last_page=2),
        ]
        transport = _make_transport(pages)
        get_calls: list[httpx.Request] = []

        real_client_cls = httpx.Client

        def _factory(*args: Any, **kwargs: Any) -> httpx.Client:
            kwargs.pop("timeout", None)
            client = real_client_cls(transport=transport)
            original_get = client.get

            def tracked_get(url: Any, **kw: Any) -> httpx.Response:
                resp = original_get(url, **kw)
                get_calls.append(resp.request)
                return resp

            client.get = tracked_get  # type: ignore[method-assign]
            return client

        with patch("src.integrations.arbeitnow.httpx.Client", side_effect=_factory):
            result = arbeitnow.fetch_arbeitnow_jobs(max_pages=5)

        assert len(result) == 2
        assert len(get_calls) == 2  # NON 5: si è fermato a last_page=2

    def test_fetch_arbeitnow_filters_non_remote_when_remote_only_true(self) -> None:
        """Item con ``remote=False`` viene scartato in normalizzazione."""
        pages = [
            _page_payload(
                [
                    _job("remote-yes", remote=True),
                    _job("remote-no", remote=False),
                    _job("remote-yes-2", remote=True),
                ],
                current_page=1,
                last_page=1,
            )
        ]
        transport = _make_transport(pages)
        with _patch_client(transport):
            result = arbeitnow.fetch_arbeitnow_jobs(max_pages=1, remote_only=True)

        ext_ids = {r["external_id"] for r in result}
        assert ext_ids == {"remote-yes", "remote-yes-2"}
        assert "remote-no" not in ext_ids

    def test_fetch_arbeitnow_keeps_non_remote_when_remote_only_false(self) -> None:
        """Con flag off, anche gli on-site sono inclusi."""
        pages = [
            _page_payload(
                [
                    _job("remote-yes", remote=True),
                    _job("onsite-1", remote=False),
                ],
                current_page=1,
                last_page=1,
            )
        ]
        transport = _make_transport(pages)
        with _patch_client(transport):
            result = arbeitnow.fetch_arbeitnow_jobs(max_pages=1, remote_only=False)

        ext_ids = {r["external_id"] for r in result}
        assert ext_ids == {"remote-yes", "onsite-1"}

    def test_fetch_arbeitnow_handles_http_error_returns_empty(self) -> None:
        """503 alla prima pagina → nessuna eccezione, lista vuota."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="upstream busy")

        transport = httpx.MockTransport(handler)
        with _patch_client(transport):
            result = arbeitnow.fetch_arbeitnow_jobs(max_pages=3)

        assert result == []

    def test_fetch_arbeitnow_handles_unix_timestamp_to_datetime(self) -> None:
        """``created_at: 1717689600`` → datetime UTC corretto."""
        pages = [
            _page_payload(
                [_job("ts-job", created_at=1717689600)],
                current_page=1,
                last_page=1,
            )
        ]
        transport = _make_transport(pages)
        with _patch_client(transport):
            result = arbeitnow.fetch_arbeitnow_jobs(max_pages=1)

        assert len(result) == 1
        posted = result[0]["posted_at"]
        assert isinstance(posted, datetime)
        assert posted.tzinfo is not None
        # 1717689600 = 2024-06-06 16:00:00 UTC
        assert posted == datetime(2024, 6, 6, 16, 0, 0, tzinfo=UTC)

    def test_fetch_arbeitnow_normalizes_job_types_list(self) -> None:
        """``["full-time"]`` → ``contract_type="full_time"`` (trattino → underscore)."""
        pages = [
            _page_payload(
                [
                    _job("ft-1", job_types=["full-time"]),
                    _job("pt-1", job_types=["part-time", "contract"]),
                    _job("none-1", job_types=[]),
                ],
                current_page=1,
                last_page=1,
            )
        ]
        transport = _make_transport(pages)
        with _patch_client(transport):
            result = arbeitnow.fetch_arbeitnow_jobs(max_pages=1)

        by_id = {r["external_id"]: r for r in result}
        assert by_id["ft-1"]["contract_type"] == "full_time"
        # Solo la PRIMA voce della lista è considerata
        assert by_id["pt-1"]["contract_type"] == "part_time"
        assert by_id["none-1"]["contract_type"] == ""


class TestParsing:
    def test_parse_created_at_returns_none_on_garbage(self) -> None:
        assert arbeitnow._parse_created_at(None) is None
        assert arbeitnow._parse_created_at("") is None
        assert arbeitnow._parse_created_at("not-a-number") is None

    def test_parse_created_at_handles_string_timestamp(self) -> None:
        dt = arbeitnow._parse_created_at("1717689600")
        assert dt == datetime(2024, 6, 6, 16, 0, 0, tzinfo=UTC)
