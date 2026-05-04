"""Test client We Work Remotely (RSS) per il layer ingest WorldWild.

Coverage: normalizzazione canonica, split title `COMPANY: ROLE`, fallback
external_id, parsing pub_date, estrazione category, graceful degradation
su HTTP error e RSS malformato.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from src.integrations import weworkremotely as wwr_mod


def _build_rss(items_xml: str) -> str:
    """Wrap items in minimal RSS envelope."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>WWR DevOps</title>
<link>https://weworkremotely.com</link>
<description>DevOps remote jobs</description>
{items_xml}
</channel></rss>"""


def _mock_client_returning(text: str, status: int = 200) -> Any:
    """Build a mock httpx.Client factory that returns a controlled Response."""

    class _MockClient:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return httpx.Response(status, text=text, request=httpx.Request("GET", url))

    return _MockClient


# ---------------------------------------------------------------------------
# 1. Basic normalization
# ---------------------------------------------------------------------------


def test_fetch_weworkremotely_basic_normalization():
    rss = _build_rss(
        """
<item>
  <title>ACME Inc: Senior DevOps Engineer</title>
  <link>https://weworkremotely.com/jobs/abc-1</link>
  <guid isPermaLink="false">wwr-abc-1</guid>
  <pubDate>Sat, 01 Jun 2024 10:30:00 +0000</pubDate>
  <description>&lt;p&gt;K8s + Terraform&lt;/p&gt;</description>
  <category>DevOps</category>
</item>
<item>
  <title>BetaCo: SRE</title>
  <link>https://weworkremotely.com/jobs/abc-2</link>
  <guid isPermaLink="false">wwr-abc-2</guid>
  <pubDate>Sun, 02 Jun 2024 09:00:00 +0000</pubDate>
  <description>&lt;p&gt;Reliability&lt;/p&gt;</description>
  <category>DevOps</category>
</item>
"""
    )

    with patch.object(wwr_mod.httpx, "Client", _mock_client_returning(rss)):
        out = wwr_mod.fetch_weworkremotely_jobs(category="remote-devops-sysadmin-jobs")

    assert len(out) == 2
    first = out[0]
    assert first["source"] == "weworkremotely"
    assert first["external_id"] == "wwr-abc-1"
    assert first["title"] == "Senior DevOps Engineer"
    assert first["company"] == "ACME Inc"
    assert first["url"] == "https://weworkremotely.com/jobs/abc-1"
    assert first["location"] == "Remote"
    assert first["category"] == "DevOps"
    assert first["salary_min"] is None
    assert first["salary_max"] is None
    assert first["salary_currency"] == ""
    assert first["contract_type"] == ""


# ---------------------------------------------------------------------------
# 2. Title split with colon
# ---------------------------------------------------------------------------


def test_fetch_weworkremotely_splits_title_company_from_colon():
    rss = _build_rss(
        """
<item>
  <title>Cool Co: Backend Engineer</title>
  <link>https://wwr/x</link>
  <guid>wwr-x</guid>
  <pubDate>Mon, 03 Jun 2024 12:00:00 +0000</pubDate>
</item>
"""
    )
    with patch.object(wwr_mod.httpx, "Client", _mock_client_returning(rss)):
        out = wwr_mod.fetch_weworkremotely_jobs()
    assert out[0]["company"] == "Cool Co"
    assert out[0]["title"] == "Backend Engineer"


# ---------------------------------------------------------------------------
# 3. Title without colon → no company prefix
# ---------------------------------------------------------------------------


def test_fetch_weworkremotely_handles_title_without_colon():
    rss = _build_rss(
        """
<item>
  <title>Senior DevOps Engineer</title>
  <link>https://wwr/y</link>
  <guid>wwr-y</guid>
  <pubDate>Tue, 04 Jun 2024 12:00:00 +0000</pubDate>
</item>
"""
    )
    with patch.object(wwr_mod.httpx, "Client", _mock_client_returning(rss)):
        out = wwr_mod.fetch_weworkremotely_jobs()
    assert out[0]["company"] == ""
    assert out[0]["title"] == "Senior DevOps Engineer"


# ---------------------------------------------------------------------------
# 4. GUID used as external_id
# ---------------------------------------------------------------------------


def test_fetch_weworkremotely_uses_guid_as_external_id():
    rss = _build_rss(
        """
<item>
  <title>Co: Role</title>
  <link>https://wwr/z</link>
  <guid>unique-guid-123</guid>
  <pubDate>Wed, 05 Jun 2024 12:00:00 +0000</pubDate>
</item>
"""
    )
    with patch.object(wwr_mod.httpx, "Client", _mock_client_returning(rss)):
        out = wwr_mod.fetch_weworkremotely_jobs()
    assert out[0]["external_id"] == "unique-guid-123"


# ---------------------------------------------------------------------------
# 5. Fallback to link when guid missing
# ---------------------------------------------------------------------------


def test_fetch_weworkremotely_falls_back_to_link_when_no_guid():
    rss = _build_rss(
        """
<item>
  <title>Co: Role</title>
  <link>https://wwr/no-guid-here</link>
  <pubDate>Thu, 06 Jun 2024 12:00:00 +0000</pubDate>
</item>
"""
    )
    with patch.object(wwr_mod.httpx, "Client", _mock_client_returning(rss)):
        out = wwr_mod.fetch_weworkremotely_jobs()
    # feedparser di default copia link in id quando guid manca
    assert out[0]["external_id"] == "https://wwr/no-guid-here"


# ---------------------------------------------------------------------------
# 6. pubDate parsed to UTC datetime
# ---------------------------------------------------------------------------


def test_fetch_weworkremotely_parses_pub_date_to_utc():
    rss = _build_rss(
        """
<item>
  <title>Co: Role</title>
  <link>https://wwr/d</link>
  <guid>wwr-d</guid>
  <pubDate>Sat, 01 Jun 2024 10:30:00 +0000</pubDate>
</item>
"""
    )
    with patch.object(wwr_mod.httpx, "Client", _mock_client_returning(rss)):
        out = wwr_mod.fetch_weworkremotely_jobs()
    posted = out[0]["posted_at"]
    assert posted is not None
    assert posted.year == 2024
    assert posted.month == 6
    assert posted.day == 1
    assert posted.hour == 10
    assert posted.minute == 30
    assert posted.tzinfo is not None


# ---------------------------------------------------------------------------
# 7. First category term extracted
# ---------------------------------------------------------------------------


def test_fetch_weworkremotely_extracts_first_category_term():
    rss = _build_rss(
        """
<item>
  <title>Co: Role</title>
  <link>https://wwr/c</link>
  <guid>wwr-c</guid>
  <pubDate>Sat, 01 Jun 2024 10:30:00 +0000</pubDate>
  <category>DevOps</category>
  <category>SysAdmin</category>
</item>
"""
    )
    with patch.object(wwr_mod.httpx, "Client", _mock_client_returning(rss)):
        out = wwr_mod.fetch_weworkremotely_jobs()
    assert out[0]["category"] == "DevOps"


# ---------------------------------------------------------------------------
# 8. HTTP error → return [] graceful
# ---------------------------------------------------------------------------


def test_fetch_weworkremotely_handles_http_error_returns_empty():
    class _ErrClient:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return httpx.Response(500, text="server error", request=httpx.Request("GET", url))

    with patch.object(wwr_mod.httpx, "Client", _ErrClient):
        out = wwr_mod.fetch_weworkremotely_jobs()
    assert out == []


# ---------------------------------------------------------------------------
# 9. Malformed RSS → graceful empty
# ---------------------------------------------------------------------------


def test_fetch_weworkremotely_handles_malformed_rss_returns_empty():
    # not even XML — feedparser tollera ma entries=[]
    with patch.object(wwr_mod.httpx, "Client", _mock_client_returning("totally not rss")):
        out = wwr_mod.fetch_weworkremotely_jobs()
    assert out == []


# ---------------------------------------------------------------------------
# 10. Empty channel → empty list
# ---------------------------------------------------------------------------


def test_fetch_weworkremotely_empty_channel_returns_empty():
    rss = _build_rss("")
    with patch.object(wwr_mod.httpx, "Client", _mock_client_returning(rss)):
        out = wwr_mod.fetch_weworkremotely_jobs()
    assert out == []


# ---------------------------------------------------------------------------
# 11. Item missing link is skipped (no external_id base)
# ---------------------------------------------------------------------------


def test_fetch_weworkremotely_skips_item_without_title():
    """Item senza title viene skippato (essenziali mancanti, sarebbe spazzatura)."""
    rss = _build_rss(
        """
<item>
  <link>https://wwr/no-title</link>
  <guid>wwr-no-title</guid>
  <pubDate>Sat, 01 Jun 2024 10:30:00 +0000</pubDate>
</item>
<item>
  <title>Co2: Role2</title>
  <link>https://wwr/has-title</link>
  <guid>wwr-has-title</guid>
  <pubDate>Sat, 01 Jun 2024 10:30:00 +0000</pubDate>
</item>
"""
    )
    with patch.object(wwr_mod.httpx, "Client", _mock_client_returning(rss)):
        out = wwr_mod.fetch_weworkremotely_jobs()
    assert len(out) == 1
    assert out[0]["external_id"] == "wwr-has-title"


@pytest.mark.parametrize(
    "category",
    [
        "remote-devops-sysadmin-jobs",
        "remote-programming-jobs",
        "remote-design-jobs",
    ],
)
def test_fetch_weworkremotely_uses_category_in_url(category, monkeypatch):
    """category param confluisce nell'URL endpoint."""
    captured: dict[str, str] = {}

    class _CapturingClient:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            captured["url"] = url
            return httpx.Response(200, text=_build_rss(""), request=httpx.Request("GET", url))

    with patch.object(wwr_mod.httpx, "Client", _CapturingClient):
        wwr_mod.fetch_weworkremotely_jobs(category=category)

    assert category in captured["url"]
    assert captured["url"].endswith("/jobs.rss")
