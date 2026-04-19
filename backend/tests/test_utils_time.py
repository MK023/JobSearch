"""Tests for Europe/Rome timezone conversion helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from zoneinfo import ZoneInfo

from src.interview.service import format_date, format_time
from src.utils.time import ITALY_TZ, italy_now, to_italy


class TestToItaly:
    def test_utc_aware_datetime_converted(self):
        # 2026-07-15 12:00 UTC → 14:00 CEST
        dt = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
        local = to_italy(dt)
        assert local.hour == 14
        assert local.tzinfo == ITALY_TZ

    def test_winter_dst_off(self):
        # 2026-01-15 12:00 UTC → 13:00 CET (no DST)
        dt = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        local = to_italy(dt)
        assert local.hour == 13

    def test_naive_datetime_assumed_utc(self):
        dt = datetime(2026, 7, 15, 12, 0)  # naive
        local = to_italy(dt)
        assert local.hour == 14
        assert local.tzinfo == ITALY_TZ

    def test_other_timezone_converted(self):
        # 2026-07-15 12:00 in New York (EDT = UTC-4) → 18:00 CEST
        ny = timezone(offset=datetime.now().astimezone(ZoneInfo("America/New_York")).utcoffset())  # noqa: DTZ005
        _ = ny  # unused, illustrative
        dt = datetime(2026, 7, 15, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        local = to_italy(dt)
        assert local.hour == 18

    def test_iso_string_parsed(self):
        local = to_italy("2026-07-15T12:00:00+00:00")
        assert isinstance(local, datetime)
        assert local.hour == 14

    def test_iso_string_naive_assumed_utc(self):
        local = to_italy("2026-07-15T12:00:00")
        assert isinstance(local, datetime)
        assert local.hour == 14

    def test_none_returned_as_is(self):
        assert to_italy(None) is None

    def test_empty_string_returned_as_is(self):
        assert to_italy("") == ""

    def test_invalid_string_returned_as_is(self):
        assert to_italy("not a date") == "not a date"

    def test_non_datetime_value_returned_as_is(self):
        assert to_italy(42) == 42


class TestItalyNow:
    def test_returns_aware_italy_tz(self):
        now = italy_now()
        assert now.tzinfo == ITALY_TZ


class TestFormatHelpers:
    def test_format_date_uses_italy_day(self):
        # 2026-03-15 23:30 UTC → 2026-03-16 00:30 CET: different calendar day
        dt = datetime(2026, 3, 15, 23, 30, tzinfo=UTC)
        result = format_date(dt)
        # 2026-03-16 in Italy, so "16 mar 2026"
        assert result == "16 mar 2026"

    def test_format_time_uses_italy_clock(self):
        start = datetime(2026, 7, 22, 14, 0, tzinfo=UTC)  # 16:00 CEST
        end = datetime(2026, 7, 22, 15, 30, tzinfo=UTC)  # 17:30 CEST
        assert format_time(start, end) == "16:00 – 17:30"

    def test_format_time_no_end(self):
        start = datetime(2026, 7, 22, 14, 0, tzinfo=UTC)
        assert format_time(start, None) == "16:00"
