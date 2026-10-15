"""v1.6.0 CR-033: Fundraiser module API (module switch, fundraisers)."""
from __future__ import annotations

import datetime as dt

import os

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from .. import audit
from ..deps import Ctx, get_db, require
from ..errors import validation
from ..schemas import ReasonIn, FundraiserBucketIn, FundraiserIn, FundraiserLineIn, FundraiserPreviewIn, ModulesIn
from ..services import fundraisers as svc
from ..services.checkprint import service as checks_svc

router = APIRouter(prefix="/api", tags=["fundraisers"])


def _modules(db: Session, ws_id: int) -> dict:
    return {"fundraisers": svc.module_enabled(db, ws_id), "checks": checks_svc.module_enabled(db, ws_id)}


@router.get("/system/modules")
def modules(db: Session = Depends(get_db), ctx: Ctx = Depends(require("modules.manage"))):
    return _modules(db, ctx.workspace_id)


@router.put("/system/modules")
def set_modules(body: ModulesIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("modules.manage"))):
    if body.fundraisers is not None:
        svc.set_module(db, ctx, body.fundraisers)
    if body.checks is not None:   # 2.0.0 (#156)
        checks_svc.set_module(db, ctx, body.checks)
    db.commit()
    return _modules(db, ctx.workspace_id)


def viewer(db: Session = Depends(get_db), ctx: Ctx = Depends(require("fundraiser.view"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


def manager(db: Session = Depends(get_db), ctx: Ctx = Depends(require("fundraiser.manage"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


@router.get("/fundraisers")
def list_fundraisers(fiscal_year_id: int | None = None, upcoming: bool = False, include_archived: bool = False,
                     db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    return svc.list_out(db, ctx, fiscal_year_id, upcoming, include_archived)


@router.get("/fundraisers/budget-options")
def budget_options(start_date: dt.date = Query(...), end_date: dt.date | None = None,
                   db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    return svc.budget_options(db, ctx, start_date, end_date or start_date)


@router.post("/fundraisers/preview")
def preview(body: FundraiserPreviewIn, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    return svc.preview(db, ctx, body.budget_ids, body.filter_text, body.filter_regex)


@router.post("/fundraisers", status_code=201)
def create(body: FundraiserIn, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    f = svc.create(db, ctx, body)
    db.commit()
    return svc.detail(db, ctx, f)


@router.get("/fundraisers/{fid}")
def get_one(fid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    return svc.detail(db, ctx, svc.get(db, ctx, fid))


@router.put("/fundraisers/{fid}")
def update(fid: int, body: FundraiserIn, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    f = svc.update(db, ctx, svc.get(db, ctx, fid), body)
    db.commit()
    return svc.detail(db, ctx, f)


@router.post("/fundraisers/{fid}/archive")
def archive(fid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    f = svc.set_archived(db, ctx, svc.get(db, ctx, fid), True)
    db.commit()
    return svc.detail(db, ctx, f)


@router.post("/fundraisers/{fid}/restore")
def restore(fid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    f = svc.set_archived(db, ctx, svc.get(db, ctx, fid), False)
    db.commit()
    return svc.detail(db, ctx, f)


@router.delete("/fundraisers/{fid}")
def delete(fid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    svc.delete(db, ctx, svc.get(db, ctx, fid))
    db.commit()
    return {"deleted": True}


# ------------------------------------------------------------------ v1.6.1 CR-034: manage (Budget Manager, Register User)
def line_manager(db: Session = Depends(get_db), ctx: Ctx = Depends(require("fundraiser.lines"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


@router.post("/fundraisers/{fid}/buckets", status_code=201)
def create_bucket(fid: int, body: FundraiserBucketIn, db: Session = Depends(get_db), ctx: Ctx = Depends(line_manager)):
    f = svc.get(db, ctx, fid)
    svc.create_bucket(db, ctx, f, body)
    db.commit()
    return svc.detail(db, ctx, f)


@router.put("/fundraisers/{fid}/buckets/{bucket_id}")
def update_bucket(fid: int, bucket_id: int, body: FundraiserBucketIn, db: Session = Depends(get_db),
                  ctx: Ctx = Depends(line_manager)):
    f = svc.get(db, ctx, fid)
    svc.update_bucket(db, ctx, f, svc.get_bucket(db, f, bucket_id), body)
    db.commit()
    return svc.detail(db, ctx, f)


@router.delete("/fundraisers/{fid}/buckets/{bucket_id}")
def delete_bucket(fid: int, bucket_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(line_manager)):
    f = svc.get(db, ctx, fid)
    svc.delete_bucket(db, ctx, f, svc.get_bucket(db, f, bucket_id))
    db.commit()
    return svc.detail(db, ctx, f)


@router.put("/fundraisers/{fid}/lines/{allocation_id}")
def set_line(fid: int, allocation_id: int, body: FundraiserLineIn, db: Session = Depends(get_db),
             ctx: Ctx = Depends(line_manager)):
    f = svc.get(db, ctx, fid)
    svc.set_line(db, ctx, f, allocation_id, body)
    db.commit()
    return svc.detail(db, ctx, f)


# ------------------------------------------------------------------ v1.6.2 CR-035: fundraiser report (PDF)
@router.get("/fundraisers/{fid}/report")
def report(fid: int, request: Request, download: bool = False, db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    from ..services import reports as report_svc
    f = svc.get(db, ctx, fid)
    path, fname, summary = report_svc.build_fundraiser_report(db, ctx, request.app.state.settings, f)
    audit.record(db, ctx, "REPORT_GENERATED", "fundraiser", f.id, None, {"report": "FUNDRAISER", **summary})
    db.commit()
    headers = {"Content-Disposition": f'{"attachment" if download else "inline"}; filename="{fname}"',
               "Cache-Control": "private, no-store", "X-Frame-Options": "SAMEORIGIN",
               "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'"}
    return FileResponse(path, media_type="application/pdf", headers=headers,
                        background=BackgroundTask(lambda: os.path.exists(path) and os.unlink(path)))


# ------------------------------------------------------------------ v1.6.4 CR-037 cancel / CR-038 cash count sheet
@router.post("/fundraisers/{fid}/cancel")
def cancel(fid: int, body: ReasonIn, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    f = svc.set_cancelled(db, ctx, svc.get(db, ctx, fid), True, body.reason)
    db.commit()
    return svc.detail(db, ctx, f)


@router.post("/fundraisers/{fid}/reinstate")
def reinstate(fid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    f = svc.set_cancelled(db, ctx, svc.get(db, ctx, fid), False)
    db.commit()
    return svc.detail(db, ctx, f)


@router.get("/fundraisers/{fid}/count-sheet")
def count_sheet(fid: int, signer_id: list[int] = Query([]), signer_title: list[str] = Query([]),
                blank_lines: int = Query(0, ge=0, le=3), extra_checks: bool = True, download: bool = False,
                db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    """A blank cash count sheet (PDF) to print, fill in by hand, sign and upload under Fundraiser documents."""
    from ..services import reports as report_svc
    from ..services import signatures as sig
    f = svc.get(db, ctx, fid)
    signers = sig.resolve_signers(db, ctx, signer_id, signer_title)
    limit = report_svc.COUNT_SHEET_MAX_BLANK_WITH_NAMED if signers else report_svc.COUNT_SHEET_MAX_BLANK
    if blank_lines > limit:
        raise validation(f"At most {limit} blank signature rows can be printed"
                         f"{' next to chosen signers' if signers else ''}.", "blank_lines")
    if len(signers) + blank_lines > report_svc.COUNT_SHEET_MAX_SIGNATURES:
        raise validation(f"At most {report_svc.COUNT_SHEET_MAX_SIGNATURES} signature rows fit on the sheet.", "blank_lines")
    path, fname = report_svc.build_count_sheet(db, ctx, f, signers, blank_lines, extra_checks)
    audit.record(db, ctx, "REPORT_GENERATED", "fundraiser", f.id, None,
                 {"report": "CASH_COUNT_SHEET", "signers": len(signers), "blank_lines": blank_lines})
    db.commit()
    headers = {"Content-Disposition": f'{"attachment" if download else "inline"}; filename="{fname}"',
               "Cache-Control": "private, no-store", "X-Frame-Options": "SAMEORIGIN",
               "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'"}
    return FileResponse(path, media_type="application/pdf", headers=headers,
                        background=BackgroundTask(lambda: os.path.exists(path) and os.unlink(path)))
