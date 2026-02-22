"""Tests for anthropic client utilities (JSON parsing, hashing, cost calculation)."""

import json

import pytest

from src.integrations.anthropic_client import (
    _clean_json_text,
    _extract_and_parse_json,
    _fix_single_quotes,
    _fix_unescaped_newlines,
    _strip_markdown_wrapper,
    content_hash,
)


class TestContentHash:
    def test_produces_hex_digest(self):
        h = content_hash("my cv", "job description")
        assert len(h) == 64  # SHA-256 hex digest

    def test_same_input_same_hash(self):
        h1 = content_hash("cv text", "job text")
        h2 = content_hash("cv text", "job text")
        assert h1 == h2

    def test_different_input_different_hash(self):
        h1 = content_hash("cv text", "job A")
        h2 = content_hash("cv text", "job B")
        assert h1 != h2


class TestStripMarkdownWrapper:
    def test_strips_json_code_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = _strip_markdown_wrapper(text)
        assert result == '{"key": "value"}'

    def test_strips_plain_code_block(self):
        text = '```\n{"key": "value"}\n```'
        result = _strip_markdown_wrapper(text)
        assert result == '{"key": "value"}'

    def test_no_wrapping_unchanged(self):
        text = '{"key": "value"}'
        result = _strip_markdown_wrapper(text)
        assert result == text


class TestCleanJsonText:
    def test_removes_trailing_commas(self):
        text = '{"a": 1, "b": 2, }'
        result = _clean_json_text(text)
        assert json.loads(result) == {"a": 1, "b": 2}

    def test_removes_single_line_comments(self):
        text = '{"a": 1 // comment\n}'
        result = _clean_json_text(text)
        assert json.loads(result) == {"a": 1}

    def test_replaces_nan_with_null(self):
        text = '{"a": NaN}'
        result = _clean_json_text(text)
        assert json.loads(result) == {"a": None}

    def test_replaces_infinity(self):
        text = '{"a": Infinity}'
        result = _clean_json_text(text)
        parsed = json.loads(result)
        assert parsed["a"] is None


class TestFixUnescapedNewlines:
    def test_fixes_newlines_in_strings(self):
        text = '{"msg": "hello\nworld"}'
        result = _fix_unescaped_newlines(text)
        parsed = json.loads(result)
        assert parsed["msg"] == "hello\nworld"

    def test_preserves_newlines_outside_strings(self):
        text = '{\n"a": 1,\n"b": 2\n}'
        result = _fix_unescaped_newlines(text)
        assert json.loads(result) == {"a": 1, "b": 2}

    def test_handles_carriage_return(self):
        text = '{"msg": "line1\r\nline2"}'
        result = _fix_unescaped_newlines(text)
        parsed = json.loads(result)
        assert "line1" in parsed["msg"]
        assert "line2" in parsed["msg"]


class TestFixSingleQuotes:
    def test_converts_single_to_double_quotes(self):
        text = "{'key': 'value'}"
        result = _fix_single_quotes(text)
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_fixes_python_booleans(self):
        text = "{'flag': True, 'other': False, 'empty': None}"
        result = _fix_single_quotes(text)
        parsed = json.loads(result)
        assert parsed["flag"] is True
        assert parsed["other"] is False
        assert parsed["empty"] is None

    def test_ignores_normal_json(self):
        text = '{"key": "value"}'
        result = _fix_single_quotes(text)
        assert result == text  # unchanged


class TestExtractAndParseJson:
    def test_parses_clean_json(self):
        result = _extract_and_parse_json('{"score": 85}')
        assert result["score"] == 85

    def test_parses_markdown_wrapped(self):
        result = _extract_and_parse_json('```json\n{"score": 85}\n```')
        assert result["score"] == 85

    def test_parses_with_trailing_comma(self):
        result = _extract_and_parse_json('{"a": 1, "b": 2,}')
        assert result == {"a": 1, "b": 2}

    def test_extracts_from_surrounding_text(self):
        text = 'Here is the result:\n{"score": 90, "company": "Test"}\nDone!'
        result = _extract_and_parse_json(text)
        assert result["score"] == 90

    def test_parses_single_quoted_python_dict(self):
        text = "{'score': 75, 'company': 'Acme', 'valid': True}"
        result = _extract_and_parse_json(text)
        assert result["score"] == 75
        assert result["valid"] is True

    def test_raises_on_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_and_parse_json("this is not json at all")

    def test_handles_nested_json(self):
        text = '{"data": {"nested": [1, 2, 3]}, "ok": true}'
        result = _extract_and_parse_json(text)
        assert result["data"]["nested"] == [1, 2, 3]
