"""Tests for cover letter service."""

import uuid

from src.cover_letter.models import CoverLetter
from src.cover_letter.service import build_docx, get_cover_letter_by_id


class TestGetCoverLetterById:
    def test_returns_cover_letter(self, db_session, test_analysis):
        cl = CoverLetter(
            analysis_id=test_analysis.id,
            language="italiano",
            content="Gentile responsabile...",
            subject_lines=["Candidatura per il ruolo"],
            model_used="claude-haiku-4-5-20251001",
            tokens_input=500,
            tokens_output=300,
            cost_usd=0.002,
        )
        db_session.add(cl)
        db_session.commit()

        result = get_cover_letter_by_id(db_session, str(cl.id))
        assert result is not None
        assert result.language == "italiano"
        assert result.content == "Gentile responsabile..."

    def test_returns_none_for_missing(self, db_session):
        result = get_cover_letter_by_id(db_session, str(uuid.uuid4()))
        assert result is None

    def test_returns_none_for_invalid_uuid(self, db_session):
        result = get_cover_letter_by_id(db_session, "not-valid")
        assert result is None


class TestBuildDocx:
    def test_generates_docx(self, db_session, test_analysis):
        cl = CoverLetter(
            analysis_id=test_analysis.id,
            language="italiano",
            content="Gentile responsabile,\n\nSono interessato al ruolo.\n\nCordiali saluti.",
            subject_lines=["Candidatura"],
            model_used="claude-haiku-4-5-20251001",
        )
        db_session.add(cl)
        db_session.commit()

        buf, filename = build_docx(cl, test_analysis)
        assert filename == "Cover_Letter_TestCorp.docx"
        assert buf.getvalue()[:4] == b"PK\x03\x04"  # DOCX is a ZIP file

    def test_filename_without_company(self, db_session, test_analysis):
        test_analysis.company = ""
        cl = CoverLetter(
            analysis_id=test_analysis.id,
            content="Test content",
        )
        db_session.add(cl)
        db_session.commit()

        buf, filename = build_docx(cl, test_analysis)
        assert filename == "Cover_Letter.docx"
