"""Tests for the low-confidence Sonnet fallback in analyze_job."""

from collections import namedtuple

import pytest

from src.integrations import anthropic_client
from src.integrations.anthropic_client import MODELS, analyze_job

# Minimal Usage stub: only .input_tokens / .output_tokens are read by the code.
FakeUsage = namedtuple("FakeUsage", ["input_tokens", "output_tokens"])


@pytest.fixture
def call_log(monkeypatch):
    """Replace _call_api with a queue-driven stub.

    Each test pushes (result_dict, usage) tuples; _call_api pops them in order
    and records the model_id it was called with into `call_log["models"]`.
    """
    queue = []
    log: dict = {"models": [], "queue": queue}

    def fake_call_api(system_prompt, user_prompt, model_id, max_tokens):
        log["models"].append(model_id)
        if not queue:
            raise AssertionError(f"Unexpected _call_api invocation #{len(log['models'])} on {model_id}")
        return queue.pop(0)

    monkeypatch.setattr(anthropic_client, "_call_api", fake_call_api)
    return log


def _push(log, result, in_tokens=100, out_tokens=200):
    log["queue"].append((result, FakeUsage(input_tokens=in_tokens, output_tokens=out_tokens)))


class TestSonnetFallback:
    def test_no_fallback_when_disabled(self, call_log, monkeypatch):
        monkeypatch.setattr(anthropic_client.settings, "ai_sonnet_fallback_on_low_confidence", False)
        _push(call_log, {"confidence": "bassa", "score": 30})

        result = analyze_job("cv text", "job desc", model="haiku", cache=None)

        assert call_log["models"] == [MODELS["haiku"]]
        assert result["model_used"] == MODELS["haiku"]
        assert result["fallback_used"] is False

    def test_fallback_when_enabled_and_low_confidence(self, call_log, monkeypatch):
        monkeypatch.setattr(anthropic_client.settings, "ai_sonnet_fallback_on_low_confidence", True)
        _push(call_log, {"confidence": "bassa", "score": 30}, in_tokens=100, out_tokens=200)
        _push(call_log, {"confidence": "alta", "score": 75}, in_tokens=120, out_tokens=300)

        result = analyze_job("cv text", "job desc", model="haiku", cache=None)

        assert call_log["models"] == [MODELS["haiku"], MODELS["sonnet"]]
        assert result["model_used"] == MODELS["sonnet"]
        assert result["fallback_used"] is True
        # Sonnet result wins
        assert result["confidence"] == "alta"
        assert result["score"] == 75
        # Tokens cumulative across both passes
        assert result["tokens"]["input"] == 220
        assert result["tokens"]["output"] == 500
        assert result["tokens"]["total"] == 720
        # Cost is sum of both passes (just check it's > the single-Haiku cost)
        assert result["cost_usd"] > 0

    def test_no_fallback_when_high_confidence(self, call_log, monkeypatch):
        monkeypatch.setattr(anthropic_client.settings, "ai_sonnet_fallback_on_low_confidence", True)
        _push(call_log, {"confidence": "alta", "score": 80})

        result = analyze_job("cv text", "job desc", model="haiku", cache=None)

        assert call_log["models"] == [MODELS["haiku"]]
        assert result["model_used"] == MODELS["haiku"]
        assert result["fallback_used"] is False

    def test_no_fallback_when_already_sonnet(self, call_log, monkeypatch):
        """Avoid recursion: if user explicitly chose Sonnet, do not retry."""
        monkeypatch.setattr(anthropic_client.settings, "ai_sonnet_fallback_on_low_confidence", True)
        _push(call_log, {"confidence": "bassa", "score": 30})

        result = analyze_job("cv text", "job desc", model="sonnet", cache=None)

        assert call_log["models"] == [MODELS["sonnet"]]
        assert result["model_used"] == MODELS["sonnet"]
        assert result["fallback_used"] is False

    def test_no_fallback_when_medium_confidence(self, call_log, monkeypatch):
        """Only 'bassa' triggers fallback, not 'media'."""
        monkeypatch.setattr(anthropic_client.settings, "ai_sonnet_fallback_on_low_confidence", True)
        _push(call_log, {"confidence": "media", "score": 60})

        result = analyze_job("cv text", "job desc", model="haiku", cache=None)

        assert call_log["models"] == [MODELS["haiku"]]
        assert result["fallback_used"] is False
