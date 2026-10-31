from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..errors import AppError
from ..schemas import AttachmentOrderIn, AttachmentTypeIn
from ..services import attachments as svc

router = APIRouter(prefix="/api", tags=["attachments"])
Owner = Literal["fiscal_year", "transaction", "allocation", "fundraiser"]


@router.get("/attachments")
def list_attachments(owner_type: Owner, owner_id: int, include_removed: bool = False, db: Session = Depends(get_db),
                     ctx: Ctx = Depends(require("financial.view"))):
    return [svc.out(a) for a in svc.list_for(db, ctx, owner_type, owner_id, include_removed)]


@router.post("/attachments", status_code=201)
async def upload(request: Request, owner_type: Owner, owner_id: int, file: UploadFile = File(...),
                 document_type: Literal["APPROVAL", "AUDIT_SIGNOFF", "UNSPECIFIED"] | None = None,
                 attach_anyway: bool = False, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    svc.check_manage(ctx, owner_type)  # authorize before reading the body into memory
    data = await svc.read_limited(file)
    a = svc.store(db, ctx, request.app.state.settings, owner_type, owner_id, file.filename, data, document_type,
                  attach_anyway=attach_anyway)   # 2.4.0 (#425): the same file twice on one record needs a yes
    return svc.out(a)


@router.put("/attachments/order")
def reorder(body: AttachmentOrderIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    """2.1.0 (#259): save the order of an owner's attachments (used by every list, report and download)."""
    items = svc.reorder(db, ctx, body.owner_type, body.owner_id, body.attachment_ids)
    db.commit()
    return [svc.out(a) for a in items]


@router.get("/attachments/{att_id}")
def get_attachment(att_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    return svc.out(svc.get(db, ctx, att_id))


@router.get("/attachments/{att_id}/content")
def content(att_id: int, request: Request, download: bool = False, db: Session = Depends(get_db),
            ctx: Ctx = Depends(require("financial.view"))):
    a = svc.get(db, ctx, att_id)
    path = svc.path_for(request.app.state.settings, a)
    if not path.is_file():
        raise AppError(404, "NOT_FOUND", "Attachment content not found.")
    disp = "attachment" if download else "inline"
    ascii_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in a.original_filename)[:100]
    headers = {
        "Content-Disposition": f"{disp}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(a.original_filename)}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; object-src 'self'; "
                                   "plugin-types application/pdf; frame-ancestors 'self'",
    }
    return FileResponse(path, media_type=a.mime_type, headers=headers)


@router.post("/attachments/{att_id}/remove")
def remove(att_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    a = svc.remove(db, ctx, svc.get(db, ctx, att_id))
    db.commit()
    return svc.out(a)


@router.post("/attachments/{att_id}/document-type")
def set_document_type(att_id: int, body: AttachmentTypeIn, db: Session = Depends(get_db),
                      ctx: Ctx = Depends(require("fiscal_year.manage"))):
    a = svc.set_document_type(db, ctx, svc.get(db, ctx, att_id), body.document_type)
    db.commit()
    return svc.out(a)
