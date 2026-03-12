"""Tests for R2 service (presigned URLs, file operations).

Uses mocked boto3 client since we don't connect to real R2 in tests.
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.integrations.r2 import (
    check_object_exists,
    delete_interview_folder,
    delete_object,
    generate_presigned_get_url,
    generate_presigned_put_url,
    generate_r2_key,
    get_object_bytes,
    reset_client,
)


@pytest.fixture(autouse=True)
def _reset_r2_client():
    """Reset singleton client before each test."""
    reset_client()
    yield
    reset_client()


class TestGenerateR2Key:
    def test_generates_key_with_extension(self):
        key = generate_r2_key("abc-123", "document.pdf")
        assert key.startswith("interviews/abc-123/")
        assert key.endswith(".pdf")

    def test_generates_key_for_docx(self):
        key = generate_r2_key("abc-123", "report.docx")
        assert key.endswith(".docx")

    def test_generates_key_without_extension(self):
        key = generate_r2_key("abc-123", "noext")
        assert key.startswith("interviews/abc-123/")
        assert "." not in key.split("/")[-1]

    def test_unique_keys(self):
        key1 = generate_r2_key("abc", "file.pdf")
        key2 = generate_r2_key("abc", "file.pdf")
        assert key1 != key2

    def test_sanitizes_long_extension(self):
        key = generate_r2_key("abc", "file.verylongextension")
        ext = key.rsplit(".", 1)[-1]
        assert len(ext) <= 10


@patch("src.integrations.r2._get_r2_client")
class TestPresignedUrls:
    def test_generate_put_url(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = "https://r2.example.com/put?signed=1"
        mock_get_client.return_value = mock_client

        url = generate_presigned_put_url("interviews/abc/123.pdf", "application/pdf")

        assert url == "https://r2.example.com/put?signed=1"
        mock_client.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={
                "Bucket": "jobsearch-files",
                "Key": "interviews/abc/123.pdf",
                "ContentType": "application/pdf",
            },
            ExpiresIn=600,
        )

    def test_generate_get_url(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = "https://r2.example.com/get?signed=1"
        mock_get_client.return_value = mock_client

        url = generate_presigned_get_url("interviews/abc/123.pdf")

        assert url == "https://r2.example.com/get?signed=1"
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={
                "Bucket": "jobsearch-files",
                "Key": "interviews/abc/123.pdf",
            },
            ExpiresIn=3600,
        )


@patch("src.integrations.r2._get_r2_client")
class TestCheckObjectExists:
    def test_returns_size_when_exists(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.head_object.return_value = {"ContentLength": 12345}
        mock_get_client.return_value = mock_client

        size = check_object_exists("interviews/abc/123.pdf")
        assert size == 12345

    def test_returns_none_when_not_found(self, mock_get_client):
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "404", "Message": "Not Found"}}
        mock_client.head_object.side_effect = ClientError(error_response, "HeadObject")
        mock_get_client.return_value = mock_client

        size = check_object_exists("interviews/abc/missing.pdf")
        assert size is None


@patch("src.integrations.r2._get_r2_client")
class TestGetObjectBytes:
    def test_returns_bytes(self, mock_get_client):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"%PDF-1.4 fake content"
        mock_client.get_object.return_value = {"Body": mock_body}
        mock_get_client.return_value = mock_client

        data = get_object_bytes("interviews/abc/123.pdf")
        assert data == b"%PDF-1.4 fake content"


@patch("src.integrations.r2._get_r2_client")
class TestDeleteObject:
    def test_deletes_successfully(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = delete_object("interviews/abc/123.pdf")
        assert result is True
        mock_client.delete_object.assert_called_once()

    def test_returns_false_on_error(self, mock_get_client):
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "500", "Message": "Internal"}}
        mock_client.delete_object.side_effect = ClientError(error_response, "DeleteObject")
        mock_get_client.return_value = mock_client

        result = delete_object("interviews/abc/123.pdf")
        assert result is False


@patch("src.integrations.r2._get_r2_client")
class TestDeleteInterviewFolder:
    def test_deletes_all_files(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "interviews/abc/1.pdf"},
                {"Key": "interviews/abc/2.docx"},
            ]
        }
        mock_get_client.return_value = mock_client

        count = delete_interview_folder("abc")
        assert count == 2
        mock_client.delete_objects.assert_called_once()

    def test_returns_zero_when_empty(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {}
        mock_get_client.return_value = mock_client

        count = delete_interview_folder("abc")
        assert count == 0
