"""2.2.0 (#280): organization branding for generated reports and presentations (System/About -> Branding)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..errors import AppError, not_found
from ..services import branding as svc

router = APIRouter(prefix="/api/system/branding", tags=["administration"])


class BrandingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: str = Field(max_length=20)
    source_primary: str | None = Field(default=None, max_length=7)
    source_secondary: str | None = Field(default=None, max_length=7)
    colors: dict[str, str] | None = Field(default=None, max_length=len(svc.ROLES))
    series: list[str] | None = Field(default=None, max_length=svc.SERIES_COUNT)
    footer_text: str | None = Field(default=None, max_length=svc.FOOTER_MAX + 20)
    # 2.3.0 (#386): the dark theme (omitted = unchanged), the theme per output type, dark-background logos
    dark_preset: str | None = Field(default=None, max_length=20)
    dark_colors: dict[str, str] | None = Field(default=None, max_length=len(svc.ROLES))
    dark_series: list[str] | None = Field(default=None, max_length=svc.SERIES_COUNT)
    themes: dict[str, str] | None = Field(default=None, max_length=len(svc.OUTPUTS))
    dark_logos: bool | None = None
    confirmations: list[str] = Field(default_factory=list, max_length=5)


@router.get("")
def view(db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    return svc.view(db, ctx)


@router.put("")
def save(body: BrandingIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    out = svc.save(db, ctx, body)
    db.commit()
    return out


@router.post("/reset")
def reset(db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    out = svc.reset_palette(db, ctx)
    db.commit()
    return out


@router.post("/logo/{slot}")
async def logo_set(slot: str, file: UploadFile = File(...), db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("system.manage"))):
    """The full logo or the small mark (2.3.0 #386: or their dark-background versions, dark_full / dark_mark): PNG or
    JPEG, at most 2 MB; re-encoded as PNG without metadata."""
    data = await file.read(svc.MAX_LOGO_BYTES + 1)
    if len(data) > svc.MAX_LOGO_BYTES:
        raise AppError(413, "FILE_TOO_LARGE", "A logo may not exceed 2 MB.")
    out = svc.set_logo(db, ctx, slot, data)
    db.commit()
    return out


@router.post("/logo/{slot}/remove")
def logo_remove(slot: str, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    out = svc.set_logo(db, ctx, slot, None)
    db.commit()
    return out


@router.get("/logo/{slot}")
def logo_image(slot: str, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    png = svc.logo_png(db, ctx, slot)
    if not png:
        raise not_found("Logo")
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "Content-Disposition": 'inline; filename="logo.png"'})
