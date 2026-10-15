"""2.0.0 build 13 (#230): a picture (PNG) of a PDF the signed-in user was just given - see services/pdf_preview.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ..deps import Ctx, auth_ctx
from ..errors import AppError, not_found
from ..services import pdf_preview
from ..services.checkprint import raster

router = APIRouter(prefix="/api/pdf-preview", tags=["pdf-preview"])

MAX_PAGES = 4
MAX_SIDE_PX = 1400


@router.get("/{token}")
def picture(token: str, ctx: Ctx = Depends(auth_ctx)):
    """The first pages of the PDF as one PNG. 404 for an unknown, expired or someone else's token; 501
    PREVIEW_UNAVAILABLE where the server can't draw pictures (the screen then shows the PDF itself)."""
    pdf = pdf_preview.get(ctx.user.id, token) if len(token) <= 64 else None
    if pdf is None:
        raise not_found("Preview")
    if not raster.available():
        raise AppError(501, "PREVIEW_UNAVAILABLE", "The picture preview is not available on this server.")
    png, pages = raster.pdf_to_png(pdf, max_pages=MAX_PAGES, max_side=MAX_SIDE_PX)
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                             "X-Page-Count": str(pages)})
