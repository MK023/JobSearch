"""Unit tests for the inbox service: sanitization, dedup, validation."""

from __future__ import annotations

import uuid

import pytest

from src.analysis.models import JobAnalysis
from src.inbox.models import InboxItem, InboxStatus
from src.inbox.service import (
    InboxValidationError,
    content_hash,
    count_pending_for_user,
    ingest,
    is_allowed_host,
    sanitize_raw,
)


class TestSanitization:
    def test_strips_html_tags(self):
        dirty = "<script>alert('xss')</script>Senior Python Engineer needed for our team."
        clean = sanitize_raw(dirty)
        assert "<script>" not in clean
        assert "alert" in clean  # text content preserved
        assert "Senior Python Engineer" in clean

    def test_strips_iframe_and_attributes(self):
        dirty = '<iframe src="evil.com"></iframe>Job description here with enough content for analysis and more text to fill.'
        clean = sanitize_raw(dirty)
        assert "<iframe" not in clean
        assert "evil.com" not in clean  # attribute value gone with tag
        assert "Job description here" in clean

    def test_removes_invisible_unicode(self):
        # Zero-width space and RTL override chars
        dirty = "Software\u200bEngineer\u202ewith long description text to satisfy min length of fifty chars."
        clean = sanitize_raw(dirty)
        assert "\u200b" not in clean
        assert "\u202e" not in clean
        assert "SoftwareEngineer" in clean

    def test_normalizes_unicode(self):
        # Compose equivalence: é (NFD) becomes é (NFC)
        dirty = "Cafe\u0301 Python Engineer full stack with many years of experience and skills."
        clean = sanitize_raw(dirty)
        assert "Café" in clean

    def test_preserves_paragraph_breaks(self):
        text = "Title line\n\nBody paragraph one.\n\nBody paragraph two with enough content for min length."
        clean = sanitize_raw(text)
        assert "\n\n" in clean


class TestContentHash:
    def test_same_text_same_hash(self):
        assert content_hash("hello world") == content_hash("hello world")

    def test_different_text_different_hash(self):
        assert content_hash("a") != content_hash("b")

    def test_hash_is_hex_64(self):
        h = content_hash("anything")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestDomainWhitelist:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.linkedin.com/jobs/view/123",
            "https://it.linkedin.com/jobs/view/456",
            "https://indeed.com/viewjob?jk=abc",
            "https://it.indeed.com/viewjob?jk=xyz",
            "https://www.infojobs.it/offerta/foo",
            "https://welcometothejungle.com/en/companies/foo/jobs/bar",
            "https://remoteok.com/remote-jobs/123",
            "https://wellfound.com/jobs/456",
        ],
    )
    def test_allowed_hosts(self, url):
        assert is_allowed_host(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.com/phishing",
            "https://linkedin.com.evil.com/fake",
            "https://fakeinkedin.com/jobs",
            "http://",
            "not-a-url",
            "https://facebook.com/jobs/123",
        ],
    )
    def test_blocked_hosts(self, url):
        assert is_allowed_host(url) is False


class TestIngest:
    def test_happy_path_creates_pending_item(self, db_session, test_user):
        raw = "Senior Python Engineer needed. " * 5  # ~150 chars, well above min
        item, dedup = ingest(
            db_session,
            user_id=test_user.id,
            raw_text=raw,
            source_url="https://www.linkedin.com/jobs/view/123",
            source="linkedin",
        )
        assert dedup is False
        assert item.status == InboxStatus.PENDING.value
        assert item.content_hash != ""
        assert item.analysis_id is None

    def test_rejects_blocked_domain(self, db_session, test_user):
        raw = "Valid job description. " * 5
        with pytest.raises(InboxValidationError, match="allowlist"):
            ingest(
                db_session,
                user_id=test_user.id,
                raw_text=raw,
                source_url="https://evil.com/phishing",
                source="other",
            )

    def test_rejects_sanitized_too_short(self, db_session, test_user):
        # Raw has enough length but sanitization strips it below 50
        raw = "<script>" + "x" * 45 + "</script>"
        # After strip: 45 chars < 50 min
        with pytest.raises(InboxValidationError, match="too short"):
            ingest(
                db_session,
                user_id=test_user.id,
                raw_text=raw,
                source_url="https://www.linkedin.com/jobs/view/1",
                source="linkedin",
            )

    def test_dedup_links_to_existing_analysis(self, db_session, test_user, test_cv):
        raw = "Senior Python Engineer needed. " * 5
        from src.inbox.service import sanitize_raw as _sanitize

        sanitized = _sanitize(raw)
        from src.integrations.anthropic_client import MODELS

        # Seed an existing analysis with the same content_hash + haiku model
        existing_analysis = JobAnalysis(
            id=uuid.uuid4(),
            cv_id=test_cv.id,
            job_description=sanitized,
            content_hash=content_hash(sanitized),
            model_used=MODELS["haiku"],
        )
        db_session.add(existing_analysis)
        db_session.commit()

        item, dedup = ingest(
            db_session,
            user_id=test_user.id,
            raw_text=raw,
            source_url="https://www.linkedin.com/jobs/view/1",
            source="linkedin",
        )
        assert dedup is True
        assert item.status == InboxStatus.SKIPPED.value
        assert item.analysis_id == existing_analysis.id

    def test_pending_quota_exhausted(self, db_session, test_user):
        # Fill quota
        for i in range(3):
            db_session.add(
                InboxItem(
                    id=uuid.uuid4(),
                    user_id=test_user.id,
                    raw_text="filler " * 10,
                    content_hash=f"hash{i}",
                    status=InboxStatus.PENDING.value,
                )
            )
        db_session.commit()

        with pytest.raises(InboxValidationError, match="quota"):
            ingest(
                db_session,
                user_id=test_user.id,
                raw_text="Another job post. " * 10,
                source_url="https://www.linkedin.com/jobs/view/99",
                source="linkedin",
                max_pending=3,
            )


class TestCountPending:
    def test_counts_only_pending_and_processing(self, db_session, test_user):
        for status in [
            InboxStatus.PENDING.value,
            InboxStatus.PROCESSING.value,
            InboxStatus.DONE.value,
            InboxStatus.ERROR.value,
            InboxStatus.SKIPPED.value,
        ]:
            db_session.add(
                InboxItem(
                    id=uuid.uuid4(),
                    user_id=test_user.id,
                    raw_text="x" * 60,
                    content_hash=f"hash_{status}",
                    status=status,
                )
            )
        db_session.commit()

        assert count_pending_for_user(db_session, test_user.id) == 2
