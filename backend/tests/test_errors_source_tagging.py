"""Tests for the flow_source tagging helpers."""

from __future__ import annotations

from src.errors.source_tagging import _PATH_PREFIX_TO_SOURCE, infer_source_from_path, tag_flow_source


class TestInferSourceFromPath:
    def test_extension_path(self):
        assert infer_source_from_path("/api/v1/inbox") == "extension"
        assert infer_source_from_path("/api/v1/inbox/pending") == "extension"

    def test_mcp_import_path(self):
        assert infer_source_from_path("/api/v1/analysis/import") == "mcp"

    def test_api_analyze_path(self):
        assert infer_source_from_path("/api/v1/analyze") == "api"

    def test_cowork_form_path(self):
        assert infer_source_from_path("/analyze") == "cowork"

    def test_unrelated_path_returns_none(self):
        # /health, /dashboard, / aren't analysis flows.
        assert infer_source_from_path("/health") is None
        assert infer_source_from_path("/") is None
        assert infer_source_from_path("") is None

    def test_order_matters_most_specific_wins(self):
        # /api/v1/inbox must match "extension" before the shorter
        # /api/v1/analyze would match "api".
        first_prefix, first_source = _PATH_PREFIX_TO_SOURCE[0]
        assert first_prefix.startswith("/api/v1/inbox")
        assert first_source == "extension"


class TestTagFlowSource:
    def test_none_is_silent(self):
        # Must not raise even if sentry_sdk is importable.
        tag_flow_source(None)
        tag_flow_source("")

    def test_valid_source_is_accepted(self):
        # We can't easily assert the tag landed (sentry_sdk may be
        # mocked/disabled), but the call must complete without raising.
        tag_flow_source("extension")
        tag_flow_source("cowork")
