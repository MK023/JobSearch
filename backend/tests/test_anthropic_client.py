"""Tests for anthropic client utilities (hashing, tool-use plumbing).

The ~120 LOC of legacy parser tests (TestStripMarkdownWrapper, TestCleanJsonText,
TestFixUnescapedNewlines, TestFixSingleQuotes, TestExtractAndParseJson) were
removed when the tool-use migration eliminated all the custom JSON parsing.
Anthropic's SDK now delivers the parsed tool input as a dict directly.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.integrations import anthropic_client
from src.integrations.anthropic_client import _call_api_with_tool, content_hash


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


class TestCallApiWithTool:
    """_call_api_with_tool forces tool_use output and returns the parsed dict."""

    def _fake_message(self, tool_input: dict, input_tokens: int = 100, output_tokens: int = 50):
        tool_use_block = SimpleNamespace(type="tool_use", input=tool_input)
        usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
        return SimpleNamespace(content=[tool_use_block], usage=usage)

    def test_returns_parsed_tool_input(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.messages.create.return_value = self._fake_message({"score": 75, "role": "Dev"})
        monkeypatch.setattr(anthropic_client, "get_client", lambda: fake_client)

        result, usage = _call_api_with_tool(
            "sys",
            "user",
            "claude-haiku-4-5-20251001",
            1024,
            tool_name="t",
            tool_description="desc",
            input_schema={"type": "object", "properties": {}},
        )

        assert result == {"score": 75, "role": "Dev"}
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50

    def test_forces_specific_tool(self, monkeypatch):
        """tool_choice must pin the named tool so the model cannot skip it."""
        fake_client = MagicMock()
        fake_client.messages.create.return_value = self._fake_message({"x": 1})
        monkeypatch.setattr(anthropic_client, "get_client", lambda: fake_client)

        _call_api_with_tool(
            "sys",
            "user",
            "claude-haiku-4-5-20251001",
            1024,
            tool_name="submit_payload",
            tool_description="desc",
            input_schema={"type": "object"},
        )

        kwargs = fake_client.messages.create.call_args.kwargs
        assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_payload"}
        assert kwargs["tools"][0]["name"] == "submit_payload"
        assert kwargs["tools"][0]["input_schema"] == {"type": "object"}

    def test_raises_when_no_tool_use_block(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="oops")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        monkeypatch.setattr(anthropic_client, "get_client", lambda: fake_client)

        import pytest

        with pytest.raises(RuntimeError, match="tool_use"):
            _call_api_with_tool(
                "sys",
                "user",
                "claude-haiku-4-5-20251001",
                1024,
                tool_name="t",
                tool_description="d",
                input_schema={"type": "object"},
            )

    def test_preserves_cache_control_in_system(self, monkeypatch):
        """System prompt must keep cache_control=ephemeral so prompt caching works."""
        fake_client = MagicMock()
        fake_client.messages.create.return_value = self._fake_message({})
        monkeypatch.setattr(anthropic_client, "get_client", lambda: fake_client)

        _call_api_with_tool(
            "sys",
            "user",
            "claude-haiku-4-5-20251001",
            1024,
            tool_name="t",
            tool_description="d",
            input_schema={"type": "object"},
        )
        kwargs = fake_client.messages.create.call_args.kwargs
        assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
