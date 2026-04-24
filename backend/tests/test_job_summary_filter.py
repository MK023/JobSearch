"""Tests for the job_summary_items Jinja2 filter (_parse_job_summary in main.py)."""

from backend.src.main import _parse_job_summary


def test_list_passthrough() -> None:
    assert _parse_job_summary(["a", "b"]) == ["a", "b"]


def test_json_array_string() -> None:
    raw = '["Progettazione K8s", "CI/CD pipeline", "Scripting Python"]'
    result = _parse_job_summary(raw)
    assert result == ["Progettazione K8s", "CI/CD pipeline", "Scripting Python"]


def test_plain_string() -> None:
    assert _parse_job_summary("solo testo") == ["solo testo"]


def test_non_array_json_string() -> None:
    assert _parse_job_summary('{"key": "val"}') == ['{"key": "val"}']


def test_malformed_array_string() -> None:
    assert _parse_job_summary('["unclosed') == ['["unclosed']


def test_other_type() -> None:
    assert _parse_job_summary(42) == ["42"]


def test_whitespace_stripped() -> None:
    result = _parse_job_summary('["  item one  ", "item two"]')
    assert result == ["item one", "item two"]
