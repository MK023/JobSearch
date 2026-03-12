"""Tests for R2 and Resend configuration."""

from src.config import Settings


class TestR2Config:
    def test_r2_defaults(self):
        s = Settings(
            anthropic_api_key="test",
            database_url="sqlite:///:memory:",
            _env_file=None,
        )
        assert s.r2_bucket_name == "jobsearch-files"
        assert s.r2_access_key_id == ""
        assert s.r2_endpoint_url == ""

    def test_r2_from_env(self, monkeypatch):
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "AKID")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "SECRET")
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://xxx.r2.cloudflarestorage.com")
        monkeypatch.setenv("R2_BUCKET_NAME", "my-bucket")
        s = Settings(
            anthropic_api_key="test",
            database_url="sqlite:///:memory:",
            _env_file=None,
        )
        assert s.r2_access_key_id == "AKID"
        assert s.r2_secret_access_key == "SECRET"
        assert s.r2_endpoint_url == "https://xxx.r2.cloudflarestorage.com"
        assert s.r2_bucket_name == "my-bucket"

    def test_resend_defaults(self):
        s = Settings(
            anthropic_api_key="test",
            database_url="sqlite:///:memory:",
            _env_file=None,
        )
        assert s.resend_api_key == ""
        assert s.resend_from_email == "noreply@jobsearches.cc"
        assert s.document_reminder_email == "marco.bellingeri@gmail.com"
