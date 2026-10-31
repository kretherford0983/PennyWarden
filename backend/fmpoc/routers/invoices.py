"""2.4.0 (#251): the Invoices module API (empty module; the invoice features arrive with later 2.4.0 builds)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..services import invoices as svc

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.get("/overview")
def overview(db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.view"))):
    """The Invoices landing page: what this user may do. Refused while the module is off (BR-091)."""
    svc.require_module(db, ctx)
    return svc.overview(ctx)


@router.get("/setup")
def setup(db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.setup"))):
    """The Administrator's module setup (filled in by the Invoices build). No real invoices or products (BR-003)."""
    svc.require_module(db, ctx)
    return svc.setup(db, ctx)
