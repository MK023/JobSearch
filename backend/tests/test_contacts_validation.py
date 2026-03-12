"""Tests for contacts route validation."""

import pytest

from src.contacts.routes import VALID_SOURCES, ContactPayload


class TestContactPayload:
    def test_valid_payload(self):
        p = ContactPayload(name="Mario Rossi", email="mario@example.com", source="manual")
        assert p.name == "Mario Rossi"

    def test_name_max_length(self):
        with pytest.raises(ValueError):
            ContactPayload(name="x" * 256)

    def test_email_max_length(self):
        with pytest.raises(ValueError):
            ContactPayload(email="x" * 256)

    def test_linkedin_url_max_length(self):
        with pytest.raises(ValueError):
            ContactPayload(linkedin_url="x" * 501)


class TestValidSources:
    @pytest.mark.parametrize("source", ["manual", "linkedin", "email", "other"])
    def test_valid_sources(self, source):
        assert source in VALID_SOURCES

    @pytest.mark.parametrize("source", ["random", "api", ""])
    def test_invalid_sources(self, source):
        assert source not in VALID_SOURCES
