"""Document discovery endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_registry
from app.domain.registry import DocumentRegistry
from app.domain.schemas import SupportedDocumentsResponse

router = APIRouter(prefix="/v1", tags=["documents"])


@router.get("/documents", response_model=SupportedDocumentsResponse)
def list_supported_documents(
    registry: Annotated[DocumentRegistry, Depends(get_registry)],
) -> SupportedDocumentsResponse:
    """Return all supported document types registered in the service."""
    documents = registry.list_documents()
    return SupportedDocumentsResponse(documents=documents, total=len(documents))
