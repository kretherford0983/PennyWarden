from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..models import FiscalYear
from ..schemas import (ApprovalNoAttachmentIn, FiscalYearApproveIn, FiscalYearCloseIn, FiscalYearCreateIn,
                       FiscalYearUpdateIn)
from ..services import budgets as bsvc
from ..services import fiscal_years as svc
from ..services import register as rsvc
from ..services.common import get_scoped

router = APIRouter(prefix="/api/fiscal-years", tags=["fiscal-years"])


@router.get("")
def list_fiscal_years(db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    return [svc.out(f) for f in svc.list_all(db, ctx.workspace_id)]


@router.get("/natural")
def natural(date: dt.date = Query(...), db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    """Fiscal Year(s) naturally covering a Transaction Date (default/ambiguity/closest)."""
    return rsvc.natural_fy_info(db, ctx.workspace_id, date)


@router.post("/continuity-check")
def continuity_check(body: FiscalYearUpdateIn, db: Session = Depends(get_db),
                     ctx: Ctx = Depends(require("fiscal_year.manage"))):
    if not body.start_date or not body.end_date:
        return {"warnings": []}
    return {"warnings": [w.as_dict() for w in svc.continuity_warnings(db, ctx.workspace_id, body.start_date,
                                                                          body.end_date, None)]}


@router.post("", status_code=201)
def create(body: FiscalYearCreateIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("fiscal_year.manage"))):
    fy = svc.create(db, ctx, body)
    db.commit()
    return svc.out(fy)


@router.get("/{fy_id}")
def detail(fy_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    fy = get_scoped(db, FiscalYear, fy_id, ctx, "Fiscal Year")
    from ..services import bank_accounts as bank
    return {**svc.out(fy), "budgets": bsvc.tree(db, fy), "closure": svc.closure_check(db, fy),
            "document_counts": svc.fy_document_counts(db, fy),
            "balance_changes_after_close": bank.changes_after_close(db, fy)}      # 2.3.0 (#391)


@router.patch("/{fy_id}")
def update(fy_id: int, body: FiscalYearUpdateIn, db: Session = Depends(get_db),
           ctx: Ctx = Depends(require("fiscal_year.manage"))):
    fy = svc.update(db, ctx, get_scoped(db, FiscalYear, fy_id, ctx, "Fiscal Year"), body)
    db.commit()
    return svc.out(fy)


@router.get("/{fy_id}/closure-check")
def closure_check(fy_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    return svc.closure_check(db, get_scoped(db, FiscalYear, fy_id, ctx, "Fiscal Year"))


@router.get("/{fy_id}/documentation-review")
def documentation_review(fy_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    from ..services import documentation
    fy = get_scoped(db, FiscalYear, fy_id, ctx, "Fiscal Year")
    return {"fiscal_year_id": fy.id, "items": documentation.review(db, fy)}


@router.post("/{fy_id}/approve")
def approve(fy_id: int, body: FiscalYearApproveIn, db: Session = Depends(get_db),
            ctx: Ctx = Depends(require("fiscal_year.manage"))):
    fy = svc.approve(db, ctx, get_scoped(db, FiscalYear, fy_id, ctx, "Fiscal Year"), body.confirm_irreversible)
    db.commit()
    return svc.out(fy)


@router.post("/{fy_id}/approval-no-attachment")
def approval_no_attachment(fy_id: int, body: ApprovalNoAttachmentIn, db: Session = Depends(get_db),
                           ctx: Ctx = Depends(require("fiscal_year.manage"))):
    fy = svc.set_approval_no_attachment(db, ctx, get_scoped(db, FiscalYear, fy_id, ctx, "Fiscal Year"),
                                        body.no_attachment, body.reason)
    db.commit()
    return svc.out(fy)


@router.post("/{fy_id}/close")
def close(fy_id: int, body: FiscalYearCloseIn, request: Request, db: Session = Depends(get_db),
          ctx: Ctx = Depends(require("fiscal_year.manage"))):
    fy = svc.close(db, ctx, get_scoped(db, FiscalYear, fy_id, ctx, "Fiscal Year"), body.confirm_reviewed)
    # v1.3 CR-008: the Close report is generated in the same database transaction and kept as a permanent,
    # system-generated Fiscal Year document. If it cannot be produced, the closure is rolled back.
    import os

    from ..services import attachments as asvc
    from ..services import reports as report_svc
    settings = request.app.state.settings
    # v1.6.2 CR-035: the stored Close report includes the year's fundraisers (when the module is on)
    tmp, fname, summary = report_svc.build_audit_report(db, ctx, settings, fy, None, True, layout="close", fundraisers=True)
    stored = None
    try:
        with open(tmp, "rb") as fh:
            data = fh.read()
        _att, stored = asvc.store_system_fy_document(db, ctx, settings, fy, fname, data, asvc.CLOSE_REPORT)
        db.commit()
    except Exception:
        db.rollback()
        if stored is not None and stored.exists():
            stored.unlink()
        raise
    finally:
        os.path.exists(tmp) and os.unlink(tmp)
    return svc.out(fy)
