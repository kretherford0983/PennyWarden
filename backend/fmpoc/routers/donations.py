"""2.1.0 (#312): Donations module API - donation receipt letters.

Setup (Administrators, donation.setup): the organization's EIN and mailing address, the receipt template and signer,
a live preview and a test print with sample data only (BR-003).
Deposits (donation.view: Budget Managers, Budget Users, Register Users, Auditors): a deposit's donation lines and
receipts. Marking lines and printing receipts: Register Users (donation.print).
Every endpoint needs the module switched on (404 MODULE_DISABLED otherwise)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import audit
from ..deps import Ctx, get_db, require
from ..errors import AppError
from ..services import donations as svc
from ..services.checkprint import raster
from .checks import _pdf

router = APIRouter(prefix="/api/donations", tags=["donations"])


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SetupIn(In):
    config: dict


class PreviewIn(In):
    config: dict | None = None        # the setup screen's unsaved settings


class LinesIn(In):
    lines: list[svc.LineIn] = Field(max_length=200)


class ReceiptIn(In):
    donor_entity_id: int
    confirmations: list[str] = Field(default_factory=list, max_length=10)


def setup_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(require("donation.setup"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


def view_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(require("donation.view"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


def print_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(require("donation.print"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


@router.get("/setup")
def get_setup(db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    return svc.setup_out(db, ctx)


@router.put("/setup")
def save_setup(body: SetupIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    svc.save_config(db, ctx, body.config)
    db.commit()
    return svc.setup_out(db, ctx)


@router.post("/setup/preview")
def setup_preview(body: PreviewIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    """The live preview with sample data (unsaved settings). Nothing is printed or stored, so not audited."""
    return _pdf(ctx, svc.sample_pdf(db, ctx, body.config), "receipt-preview.pdf")


@router.post("/setup/preview-image")
def setup_preview_image(body: PreviewIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    if not raster.available():
        raise AppError(501, "PREVIEW_UNAVAILABLE", "The picture preview is not available on this server.")
    png, pages = raster.pdf_to_png(svc.sample_pdf(db, ctx, body.config))
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "X-Page-Count": str(pages)})


@router.post("/setup/test-print")
def setup_test_print(body: PreviewIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    pdf = svc.sample_pdf(db, ctx, body.config)
    audit.record(db, ctx, "DONATION_RECEIPT_TEST", "donation_settings", None, None,
                 {"unsaved_settings": body.config is not None})
    db.commit()
    return _pdf(ctx, pdf, "receipt-test-print.pdf")


@router.get("/transactions/{txn_id}")
def transaction(txn_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(view_ctx)):
    return svc.transaction_out(db, ctx, svc.get_deposit(db, ctx, txn_id))


@router.put("/transactions/{txn_id}/lines")
def set_lines(txn_id: int, body: LinesIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    t = svc.get_deposit(db, ctx, txn_id)
    svc.set_lines(db, ctx, t, body.lines)
    db.commit()
    return svc.transaction_out(db, ctx, t)


@router.post("/transactions/{txn_id}/receipts")
def print_receipt(txn_id: int, body: ReceiptIn, request: Request, db: Session = Depends(get_db),
                  ctx: Ctx = Depends(print_ctx)):
    t = svc.get_deposit(db, ctx, txn_id)
    pdf, r = svc.print_receipt(db, ctx, request.app.state.settings, t, body.donor_entity_id, body.confirmations)
    resp = _pdf(ctx, pdf, f"receipt-{r.number}{'-duplicate' if r.kind == svc.DUPLICATE else ''}.pdf")
    resp.headers["X-Receipt-Number"] = r.number
    resp.headers["X-Receipt-Kind"] = r.kind
    return resp
