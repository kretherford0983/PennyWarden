"""2.3.0 (#395): the shared Signers page - one list of signers (name, title, optional signature image) tagged for
the areas they may be used in (checks, payment cover letters, donation receipts and statements). Administrators only
(checks.setup or donation.setup), shown while Payments or Donations is on, like the envelope library. The signature
image is never downloadable: only a low-resolution SAMPLE is returned (the setup previews show the real one)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..deps import Ctx, auth_ctx, get_db
from ..errors import AppError, forbidden
from ..services import envelopes as env_lib
from ..services import signers as sg
from ..services.checkprint import service as cp

router = APIRouter(prefix="/api/signers", tags=["signers"])


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SignerIn(In):
    name: str = Field(max_length=120)
    title: str | None = Field(default=None, max_length=80)


class AreasIn(In):
    areas: list[str] = Field(max_length=5)


class ActiveIn(In):
    active: bool


def admin_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)) -> Ctx:
    if not (ctx.has("checks.setup") or ctx.has("donation.setup")):
        raise forbidden()
    env_lib.require_any_module(db, ctx)
    return ctx


def _list(db: Session, ctx) -> dict:
    on = env_lib.enabled(db, ctx.workspace_id)
    return {"signers": [sg.out(db, ctx, s) for s in cp.list_signers(db, ctx)],
            "areas": [{"id": a, "label": sg.LABELS[a], "enabled": sg.AREA_MODULE[a] in on} for a in sg.AREAS],
            "max": cp.MAX_SIGNERS}


@router.get("")
def list_signers(db: Session = Depends(get_db), ctx: Ctx = Depends(admin_ctx)):
    return _list(db, ctx)


@router.post("", status_code=201)
async def create(request: Request, name: str = Form(..., max_length=120), title: str | None = Form(None, max_length=80),
                 areas: str = Form("", max_length=100), file: UploadFile | None = File(None),
                 db: Session = Depends(get_db), ctx: Ctx = Depends(admin_ctx)):
    data = None
    if file is not None:
        data = await file.read(cp.MAX_SIGNATURE_BYTES + 1)
        if len(data) > cp.MAX_SIGNATURE_BYTES:
            raise AppError(413, "FILE_TOO_LARGE", "A signature image may not exceed 1 MB.")
    s = cp.create_signer(db, ctx, request.app.state.key, name, title, data,
                         areas=[a for a in areas.split(",") if a.strip()])
    db.commit()
    return sg.out(db, ctx, s)


@router.put("/{signer_id}")
def update(signer_id: int, body: SignerIn, db: Session = Depends(get_db), ctx: Ctx = Depends(admin_ctx)):
    s = cp.update_signer(db, ctx, sg.get(db, ctx, signer_id), body.name, body.title)
    db.commit()
    return sg.out(db, ctx, s)


@router.put("/{signer_id}/areas")
def set_areas(signer_id: int, body: AreasIn, db: Session = Depends(get_db), ctx: Ctx = Depends(admin_ctx)):
    s = sg.set_areas(db, ctx, sg.get(db, ctx, signer_id), body.areas)
    db.commit()
    return sg.out(db, ctx, s)


@router.post("/{signer_id}/image")
async def replace_image(signer_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                        ctx: Ctx = Depends(admin_ctx)):
    s = sg.get(db, ctx, signer_id)
    data = await file.read(cp.MAX_SIGNATURE_BYTES + 1)
    if len(data) > cp.MAX_SIGNATURE_BYTES:
        raise AppError(413, "FILE_TOO_LARGE", "A signature image may not exceed 1 MB.")
    cp.replace_signature(db, ctx, request.app.state.key, s, data)
    db.commit()
    return sg.out(db, ctx, s)


@router.post("/{signer_id}/image/remove")
def remove_image(signer_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(admin_ctx)):
    s = cp.remove_signature(db, ctx, sg.get(db, ctx, signer_id))
    db.commit()
    return sg.out(db, ctx, s)


@router.post("/{signer_id}/active")
def set_active(signer_id: int, body: ActiveIn, db: Session = Depends(get_db), ctx: Ctx = Depends(admin_ctx)):
    """Retire (or bring back) a signer. Never deleted: printed copies refer to them. In use → refused."""
    s = cp.set_signer_active(db, ctx, sg.get(db, ctx, signer_id), body.active)
    db.commit()
    return sg.out(db, ctx, s)


@router.get("/{signer_id}/preview")
def preview(signer_id: int, request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(admin_ctx)):
    png = cp.signature_preview(request.app.state.key, sg.get(db, ctx, signer_id))
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store",
                                                          "X-Content-Type-Options": "nosniff"})
