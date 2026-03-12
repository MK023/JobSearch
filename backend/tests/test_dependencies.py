"""Tests for shared dependencies."""

import uuid

import pytest
from fastapi import HTTPException

from src.dependencies import validate_uuid


class TestValidateUuid:
    def test_valid_uuid(self):
        valid = str(uuid.uuid4())
        result = validate_uuid(valid)
        assert isinstance(result, uuid.UUID)

    def test_invalid_uuid(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_uuid("not-a-uuid")
        assert exc_info.value.status_code == 400

    def test_empty_string(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_uuid("")
        assert exc_info.value.status_code == 400

    def test_sql_injection_attempt(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_uuid("'; DROP TABLE users; --")
        assert exc_info.value.status_code == 400
