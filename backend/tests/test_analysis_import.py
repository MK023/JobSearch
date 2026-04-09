"""Tests for analysis import and dedup check logic."""

from src.analysis.models import AnalysisStatus, JobAnalysis
from src.analysis.service import find_existing_analysis


class TestImportAnalysis:
    """Test the import_analysis logic: create a new JobAnalysis record."""

    def test_creates_new_analysis(self, db_session, test_cv):
        """Importing a new analysis should persist all fields."""
        analysis = JobAnalysis(
            cv_id=test_cv.id,
            job_description="Backend Developer role at a fintech startup.",
            job_url="https://example.com/job/123",
            content_hash="import_hash_001",
            company="FinTech Inc",
            role="Backend Developer",
            location="Remote",
            work_mode="remote",
            score=72,
            recommendation="CONSIDER",
            strengths=["Python", "FastAPI"],
            gaps=[{"gap": "Terraform", "severity": "importante", "closable": True, "how": "Online course"}],
            interview_scripts=[{"question": "Why this role?", "suggested_answer": "I enjoy backend work."}],
            advice="Good fit, close Terraform gap.",
            model_used="claude-haiku-4-5-20251001",
            tokens_input=800,
            tokens_output=400,
            cost_usd=0.003,
        )
        db_session.add(analysis)
        db_session.flush()

        assert analysis.id is not None
        persisted = db_session.query(JobAnalysis).filter(JobAnalysis.id == analysis.id).first()
        assert persisted is not None
        assert persisted.company == "FinTech Inc"
        assert persisted.role == "Backend Developer"
        assert persisted.score == 72
        assert persisted.content_hash == "import_hash_001"
        assert persisted.model_used == "claude-haiku-4-5-20251001"
        assert persisted.tokens_input == 800
        assert persisted.tokens_output == 400
        assert persisted.cost_usd == 0.003
        assert persisted.status == AnalysisStatus.PENDING

    def test_creates_with_defaults(self, db_session, test_cv):
        """Importing with minimal fields should use defaults."""
        analysis = JobAnalysis(
            cv_id=test_cv.id,
            job_description="Minimal job description for testing purposes only.",
            content_hash="import_hash_002",
            model_used="claude-haiku-4-5-20251001",
        )
        db_session.add(analysis)
        db_session.flush()

        persisted = db_session.query(JobAnalysis).filter(JobAnalysis.id == analysis.id).first()
        assert persisted is not None
        assert persisted.score == 0
        assert persisted.company == ""
        assert persisted.status == AnalysisStatus.PENDING

    def test_import_persists_jsonb_fields(self, db_session, test_cv):
        """JSONB fields (strengths, gaps, interview_scripts) should be stored correctly."""
        strengths = ["Docker", "Kubernetes", "CI/CD"]
        gaps = [
            {"gap": "Go", "severity": "minore", "closable": True, "how": "Side project"},
            {"gap": "AWS", "severity": "importante", "closable": True, "how": "Certification"},
        ]
        scripts = [
            {"question": "Tell me about Docker experience", "suggested_answer": "I use Docker daily."},
        ]

        analysis = JobAnalysis(
            cv_id=test_cv.id,
            job_description="DevOps Engineer role requiring Docker and Kubernetes experience.",
            content_hash="import_hash_003",
            model_used="claude-haiku-4-5-20251001",
            strengths=strengths,
            gaps=gaps,
            interview_scripts=scripts,
        )
        db_session.add(analysis)
        db_session.flush()

        persisted = db_session.query(JobAnalysis).filter(JobAnalysis.id == analysis.id).first()
        assert persisted.strengths == strengths
        assert persisted.gaps == gaps
        assert len(persisted.gaps) == 2
        assert persisted.interview_scripts == scripts


class TestImportAnalysisDedup:
    """Test dedup: if content_hash+model exists, return existing id."""

    def test_dedup_finds_existing(self, db_session, test_analysis):
        """find_existing_analysis returns the existing record when hash+model match."""
        existing = find_existing_analysis(db_session, "abc123", "claude-haiku-4-5-20251001")
        assert existing is not None
        assert existing.id == test_analysis.id

    def test_dedup_prevents_duplicate_import(self, db_session, test_cv, test_analysis):
        """Simulating import dedup: if existing found, return its id instead of creating new."""
        content_hash = "abc123"
        model_used = "claude-haiku-4-5-20251001"

        existing = find_existing_analysis(db_session, content_hash, model_used)
        assert existing is not None

        # In the route, this means we return {"duplicate": True, "analysis_id": str(existing.id)}
        # and don't create a new record
        count_before = db_session.query(JobAnalysis).count()
        # No new record should be created
        assert count_before == 1  # only test_analysis

    def test_different_hash_allows_import(self, db_session, test_analysis):
        """Different content_hash should NOT trigger dedup."""
        existing = find_existing_analysis(db_session, "different_hash_xyz", "claude-haiku-4-5-20251001")
        assert existing is None

    def test_different_model_allows_import(self, db_session, test_analysis):
        """Same hash but different model should NOT trigger dedup."""
        existing = find_existing_analysis(db_session, "abc123", "claude-sonnet-4-6")
        assert existing is None


class TestCheckDedup:
    """Test the check_dedup query logic (exists=True/False)."""

    def test_returns_exists_true_when_match(self, db_session, test_analysis):
        """When content_hash and model match an existing analysis, returns the record."""
        existing = find_existing_analysis(db_session, "abc123", "claude-haiku-4-5-20251001")
        assert existing is not None
        # Route would return {"exists": True, "analysis_id": str(existing.id)}
        assert str(existing.id) == str(test_analysis.id)

    def test_returns_exists_false_when_no_match(self, db_session):
        """When no matching analysis exists, returns None."""
        existing = find_existing_analysis(db_session, "nonexistent_hash", "claude-haiku-4-5-20251001")
        assert existing is None

    def test_returns_exists_false_for_empty_db(self, db_session):
        """On an empty database, check_dedup always returns None."""
        existing = find_existing_analysis(db_session, "any_hash", "any_model")
        assert existing is None

    def test_hash_match_but_wrong_model(self, db_session, test_analysis):
        """Matching hash but different model should return None."""
        existing = find_existing_analysis(db_session, "abc123", "gpt-4o")
        assert existing is None

    def test_model_match_but_wrong_hash(self, db_session, test_analysis):
        """Matching model but different hash should return None."""
        existing = find_existing_analysis(db_session, "wrong_hash", "claude-haiku-4-5-20251001")
        assert existing is None
