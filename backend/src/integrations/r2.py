"""Cloudflare R2 service for presigned URL generation and file operations.

Uses boto3 S3-compatible API. R2 acts as an S3 drop-in replacement.
"""

import logging
import uuid
from typing import cast

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from ..config import settings
from ..interview.file_models import PRESIGNED_URL_EXPIRY_SECONDS

logger = logging.getLogger(__name__)

_client = None


def _get_r2_client():  # type: ignore[no-untyped-def]
    """Get or create the singleton boto3 S3 client for R2."""
    global _client
    if _client is None:
        if not settings.r2_endpoint_url or not settings.r2_access_key_id:
            raise RuntimeError("R2 credentials not configured. Set R2_* env vars.")
        _client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
            region_name="auto",
        )
    return _client


def reset_client() -> None:
    """Reset the singleton client (for testing)."""
    global _client
    _client = None


def generate_r2_key(interview_id: str, filename: str) -> str:
    """Generate a unique R2 object key.

    Format: interviews/{interview_id}/{uuid}.{ext}
    The UUID prevents filename collisions and path traversal attacks.
    """
    # Extract extension safely
    ext = ""
    if "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()[:10]  # Max 10 char extension
    unique_id = uuid.uuid4().hex[:12]
    if ext:
        return f"interviews/{interview_id}/{unique_id}.{ext}"
    return f"interviews/{interview_id}/{unique_id}"


def generate_presigned_put_url(r2_key: str, content_type: str) -> str:
    """Generate a presigned PUT URL for direct browser upload to R2.

    Args:
        r2_key: The R2 object key (path within the bucket).
        content_type: MIME type of the file being uploaded.

    Returns:
        Presigned URL string valid for PRESIGNED_URL_EXPIRY_SECONDS.
    """
    client = _get_r2_client()
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.r2_bucket_name,
            "Key": r2_key,
            "ContentType": content_type,
        },
        ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
    )
    return cast(str, url)


def generate_presigned_get_url(r2_key: str, expiry: int = 3600) -> str:
    """Generate a presigned GET URL to download/view a file from R2.

    Args:
        r2_key: The R2 object key.
        expiry: URL validity in seconds (default 1 hour).

    Returns:
        Presigned URL string.
    """
    client = _get_r2_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.r2_bucket_name,
            "Key": r2_key,
        },
        ExpiresIn=expiry,
    )
    return cast(str, url)


def check_object_exists(r2_key: str) -> int | None:
    """Check if an object exists in R2 via HEAD request.

    Returns:
        File size in bytes if exists, None if not found.
    """
    client = _get_r2_client()
    try:
        response = client.head_object(
            Bucket=settings.r2_bucket_name,
            Key=r2_key,
        )
        return cast(int, response["ContentLength"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return None
        raise


def get_object_bytes(r2_key: str) -> bytes:
    """Download file content from R2.

    Returns:
        Raw file bytes.

    Raises:
        ClientError: If the object doesn't exist or other S3 error.
    """
    client = _get_r2_client()
    response = client.get_object(
        Bucket=settings.r2_bucket_name,
        Key=r2_key,
    )
    return cast(bytes, response["Body"].read())


def delete_object(r2_key: str) -> bool:
    """Delete an object from R2.

    Returns:
        True if deleted (or didn't exist), False on error.
    """
    client = _get_r2_client()
    try:
        client.delete_object(
            Bucket=settings.r2_bucket_name,
            Key=r2_key,
        )
        return True
    except ClientError:
        logger.exception("Failed to delete R2 object: %s", r2_key)
        return False


def delete_interview_folder(interview_id: str) -> int:
    """Delete all files for an interview from R2.

    Returns:
        Number of objects deleted.
    """
    client = _get_r2_client()
    prefix = f"interviews/{interview_id}/"

    try:
        response = client.list_objects_v2(
            Bucket=settings.r2_bucket_name,
            Prefix=prefix,
        )
    except ClientError:
        logger.exception("Failed to list R2 objects for prefix: %s", prefix)
        return 0

    contents = response.get("Contents", [])
    if not contents:
        return 0

    objects = [{"Key": obj["Key"]} for obj in contents]
    try:
        client.delete_objects(
            Bucket=settings.r2_bucket_name,
            Delete={"Objects": objects},
        )
        return len(objects)
    except ClientError:
        logger.exception("Failed to delete R2 objects for prefix: %s", prefix)
        return 0
