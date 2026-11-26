"""FastAPI router serving the zero-build MiruID web playground UI."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

PLAYGROUND_STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "playground"
_INDEX_HTML = PLAYGROUND_STATIC_DIR / "index.html"

router = APIRouter(tags=["playground"], include_in_schema=False)


@router.get("/", response_class=FileResponse)
@router.get("/playground", response_class=FileResponse)
async def serve_playground() -> FileResponse:
    """Serve the interactive web playground HTML page."""
    return FileResponse(_INDEX_HTML, media_type="text/html")
