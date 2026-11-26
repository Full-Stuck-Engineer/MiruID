"""Document extraction API endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile, status
from fastapi.responses import JSONResponse

from app.api.dependencies import get_pipeline
from app.application.pipeline import ExtractionPipeline
from app.domain.schemas import ErrorResponse, ExtractionResponse
from app.infrastructure.config import Settings, get_settings

router = APIRouter(prefix="/v1", tags=["extraction"])

_BYTES_PER_MB = 1024 * 1024


@router.post(
    "/extract",
    response_model=ExtractionResponse[dict[str, Any]],
)
async def extract_document(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    pipeline: Annotated[ExtractionPipeline, Depends(get_pipeline)],
    settings: Annotated[Settings, Depends(get_settings)],
    country: Annotated[str | None, Form()] = None,
    doc_type: Annotated[str | None, Form()] = None,
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> ExtractionResponse[dict[str, Any]] | JSONResponse:
    """Extract and validate structured fields from an uploaded ID document image."""
    request_id = x_request_id or str(uuid.uuid4())
    request.state.request_id = request_id

    if file.content_type not in settings.api.allowed_mime_types:
        payload = ErrorResponse(
            error_code="UNSUPPORTED_MEDIA_TYPE",
            message="Unsupported image media type.",
            request_id=request_id,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=payload.model_dump(),
        )

    image_bytes = await file.read()
    if not image_bytes:
        payload = ErrorResponse(
            error_code="INVALID_IMAGE",
            message="Uploaded image file is empty.",
            request_id=request_id,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=payload.model_dump(),
        )

    max_bytes = settings.api.max_upload_size_mb * _BYTES_PER_MB
    if len(image_bytes) > max_bytes:
        payload = ErrorResponse(
            error_code="PAYLOAD_TOO_LARGE",
            message=(
                f"Uploaded image exceeds maximum allowed size of "
                f"{settings.api.max_upload_size_mb} MB."
            ),
            request_id=request_id,
        )
        return JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content=payload.model_dump(),
        )

    return await pipeline.run(image_bytes, country, doc_type, request_id=request_id)
