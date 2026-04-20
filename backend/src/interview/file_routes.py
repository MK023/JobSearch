"""Interview file upload API routes.

Flow:
1. POST /files/request-upload -> get presigned PUT URL
2. Browser uploads directly to R2 using presigned URL
3. POST /files/{file_id}/confirm -> verify upload via HEAD
4. POST /files/{file_id}/scan -> scan with Claude API
5. GET /files/interview/{interview_id} -> list all files
6. GET /files/{file_id}/download -> get presigned GET URL
7. DELETE /files/{file_id} -> delete file from R2 + DB
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..audit.service import audit
from ..dependencies import CurrentUser, DbSession, validate_uuid
from ..integrations.document_scanner import scan_document
from ..integrations.r2 import (
    check_object_exists,
    delete_object,
    generate_presigned_get_url,
    generate_presigned_put_url,
    generate_r2_key,
    get_object_bytes,
)
from .file_models import ALLOWED_CONTENT_TYPES, MAX_FILE_SIZE_BYTES, FileStatus, InterviewFile
from .file_service import (
    MAX_FILES_PER_INTERVIEW,
    confirm_upload,
    count_files_for_interview,
    create_file_record,
    delete_file_record,
    get_file_by_id,
    get_files_for_interview,
    get_interview_by_id,
    update_scan_result,
)

router = APIRouter(tags=["files"])

_FILE_NOT_FOUND_MSG = "File not found"


class RequestUploadPayload(BaseModel):
    """Input schema for requesting a presigned upload URL."""

    interview_id: str
    filename: str = Field(max_length=255)
    content_type: str = Field(max_length=100)


def _file_to_dict(file: InterviewFile, include_download_url: bool = False) -> dict[str, Any]:
    """Serialize an InterviewFile to a dict."""
    data = {
        "id": str(file.id),
        "interview_id": str(file.interview_id),
        "original_filename": file.original_filename,
        "content_type": file.content_type,
        "file_size": file.file_size,
        "status": file.status,
        "scan_result": file.scan_result,
        "created_at": file.created_at.isoformat() if file.created_at else None,
    }
    if include_download_url and file.status != FileStatus.PENDING:
        try:
            data["download_url"] = generate_presigned_get_url(str(file.r2_key))
        except Exception:
            data["download_url"] = None
    return data


@router.post("/files/request-upload")
def request_upload(
    request: Request,
    payload: RequestUploadPayload,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Generate a presigned PUT URL for direct upload to R2.

    Returns:
        - file_id: UUID of the created file record
        - upload_url: presigned PUT URL for the browser
        - r2_key: the object key in R2
    """
    interview_id = validate_uuid(payload.interview_id)

    interview = get_interview_by_id(db, interview_id)
    if not interview:
        return JSONResponse({"error": "Interview not found"}, status_code=404)

    if payload.content_type not in ALLOWED_CONTENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_CONTENT_TYPES))
        return JSONResponse(
            {"error": f"Tipo file non supportato. Tipi ammessi: {allowed}"},
            status_code=400,
        )

    current_count = count_files_for_interview(db, interview_id)
    if current_count >= MAX_FILES_PER_INTERVIEW:
        return JSONResponse(
            {"error": f"Massimo {MAX_FILES_PER_INTERVIEW} file per colloquio"},
            status_code=400,
        )

    filename = payload.filename.strip()
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return JSONResponse({"error": "Nome file non valido"}, status_code=400)

    r2_key = generate_r2_key(str(interview_id), filename)
    upload_url = generate_presigned_put_url(r2_key, payload.content_type)

    file = create_file_record(
        db,
        interview_id=interview_id,
        original_filename=filename,
        content_type=payload.content_type,
        r2_key=r2_key,
    )

    audit(db, request, "file_upload_requested", f"file_id={file.id}, name={filename}")
    db.commit()

    return JSONResponse(
        {
            "file_id": str(file.id),
            "upload_url": upload_url,
            "r2_key": r2_key,
        },
        status_code=201,
    )


@router.post("/files/{file_id}/confirm")
def confirm_file_upload(
    request: Request,
    file_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Confirm that a file was successfully uploaded to R2.

    Performs a HEAD request on R2 to verify the object exists and get its size.
    """
    fid = validate_uuid(file_id)
    file = get_file_by_id(db, fid)
    if not file:
        return JSONResponse({"error": _FILE_NOT_FOUND_MSG}, status_code=404)

    if file.status != FileStatus.PENDING:
        return JSONResponse({"error": "File already confirmed"}, status_code=400)

    # HEAD check on R2
    file_size = check_object_exists(str(file.r2_key))
    if file_size is None:
        return JSONResponse(
            {"error": "File non trovato su R2. Riprova l'upload."},
            status_code=404,
        )

    if file_size > MAX_FILE_SIZE_BYTES:
        delete_object(str(file.r2_key))
        delete_file_record(db, file)
        db.commit()
        max_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        return JSONResponse(
            {"error": f"File troppo grande. Massimo {max_mb} MB."},
            status_code=400,
        )

    confirm_upload(db, file, file_size)
    audit(db, request, "file_upload_confirmed", f"file_id={file.id}, size={file_size}")
    db.commit()

    return JSONResponse(_file_to_dict(file))


@router.post("/files/{file_id}/scan")
def scan_file(
    request: Request,
    file_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Scan a file with Claude API to check if it's been compiled.

    File must be in 'uploaded' status. Transitions to 'compiled' or 'not_compiled'.
    """
    fid = validate_uuid(file_id)
    file = get_file_by_id(db, fid)
    if not file:
        return JSONResponse({"error": _FILE_NOT_FOUND_MSG}, status_code=404)

    if file.status not in (FileStatus.UPLOADED, FileStatus.SCAN_ERROR):
        return JSONResponse(
            {"error": f"Il file non puo essere scansionato (stato: {file.status})"},
            status_code=400,
        )

    # Download file from R2
    try:
        file_bytes = get_object_bytes(str(file.r2_key))
    except Exception:
        return JSONResponse(
            {"error": "Impossibile scaricare il file da R2"},
            status_code=500,
        )

    # Scan with Claude API
    result = scan_document(
        file_bytes=file_bytes,
        filename=str(file.original_filename),
        content_type=str(file.content_type),
    )

    update_scan_result(db, file, result["status"], result["scan_result"])
    audit(
        db,
        request,
        "file_scanned",
        f"file_id={file.id}, status={result['status']}, cost=${result['cost_usd']:.4f}",
    )
    db.commit()

    return JSONResponse(
        {
            **_file_to_dict(file),
            "compiled": result["compiled"],
            "confidence": result["confidence"],
            "cost_usd": result["cost_usd"],
            "tokens": result["tokens"],
        }
    )


@router.get("/files/interview/{interview_id}")
def list_files(
    interview_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """List all files for an interview."""
    iid = validate_uuid(interview_id)

    interview = get_interview_by_id(db, iid)
    if not interview:
        return JSONResponse({"error": "Interview not found"}, status_code=404)

    files = get_files_for_interview(db, iid)
    return JSONResponse({"files": [_file_to_dict(f, include_download_url=True) for f in files]})


@router.get("/files/{file_id}/download")
def get_download_url(
    file_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Get a presigned GET URL to download a file."""
    fid = validate_uuid(file_id)
    file = get_file_by_id(db, fid)
    if not file:
        return JSONResponse({"error": _FILE_NOT_FOUND_MSG}, status_code=404)

    if file.status == FileStatus.PENDING:
        return JSONResponse({"error": "File non ancora caricato"}, status_code=400)

    download_url = generate_presigned_get_url(str(file.r2_key))
    return JSONResponse(
        {
            "download_url": download_url,
            "original_filename": file.original_filename,
        }
    )


@router.delete("/files/{file_id}")
def remove_file(
    request: Request,
    file_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Delete a file from R2 and the database."""
    fid = validate_uuid(file_id)
    file = get_file_by_id(db, fid)
    if not file:
        return JSONResponse({"error": _FILE_NOT_FOUND_MSG}, status_code=404)

    if file.status != FileStatus.PENDING:
        delete_object(str(file.r2_key))

    audit(db, request, "file_deleted", f"file_id={file.id}, name={file.original_filename}")
    delete_file_record(db, file)
    db.commit()

    return JSONResponse({"ok": True})
