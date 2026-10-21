"""v1.6.0 CR-033: Fundraiser module API (module switch, fundraisers)."""
from __future__ import annotations

import datetime as dt
from typing import Literal

import os

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from .. import audit
from ..deps import Ctx, get_db, require
from ..errors import validation
from ..schemas import (ReasonIn, FundraiserBucketIn, FundraiserCategoryIn, FundraiserFinalIn, FundraiserFyNotesIn, FundraiserIn,
                       FundraiserLineIn, FundraiserLinkIn, FundraiserSeriesIn, FundraiserSeriesMergeIn, FundraiserSeriesResultIn,
                       FundraiserNotesIn, FundraiserOrderIn,
                       FundraiserPreviewIn, ModulesIn)
from ..services import fundraiser_deck as deck  # 2.1.0 (#276); imports python-pptx at start-up
from ..services import fundraiser_summary as fs  # 2.1.0 (#275); imports python-docx at start-up
from ..services import fundraiser_fy_report as fyrep
from ..services import fundraiser_series as series
from ..services import fundraisers as svc
from ..services.checkprint import service as checks_svc
from ..services.common import get_scoped
from ..models import FiscalYear

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


# ------------------------------------------------------------------ 2.1.0 (#277): across years
@router.get("/fundraisers/continue-options")
def continue_options(start_date: dt.date = Query(...), fundraiser_id: int | None = None, db: Session = Depends(get_db),
                     ctx: Ctx = Depends(manager)):
    """For "Continues from": the latest fundraiser of each series plus unlinked ones, from earlier Fiscal Years."""
    return series.continue_options(db, ctx, start_date, fundraiser_id)


@router.get("/fundraisers/fy-report/selection")
def fy_report_selection(fiscal_year_id: int = Query(...), db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
    return {"default_ids": series.default_selection(db, ctx, fy), "notes": series.get_notes(db, ctx, fy),
            "year": series.fy_year(fy)}


@router.put("/fundraisers/fy-report/notes")
def fy_report_notes(body: FundraiserFyNotesIn, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    fy = get_scoped(db, FiscalYear, body.fiscal_year_id, ctx, "Fiscal Year")
    notes = series.set_notes(db, ctx, fy, body.notes)
    db.commit()
    return {"notes": notes}


@router.get("/fundraisers/fy-report")
def fy_report(fiscal_year_id: int = Query(...), ids: list[int] = Query(...), years: int = Query(5, ge=-1, le=50),
              targeted: bool = False, avg_years: int = Query(5, ge=1, le=20),
              format: Literal["json", "pdf", "pptx"] = "pdf", download: bool = False,
              db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    """The Fiscal Year fundraising report (PDF) or presentation (.pptx) for the chosen fundraisers."""
    from ..models import Workspace
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
    rep = series.fy_report(db, ctx, fy, ids, years=years, targeted=targeted, avg_years=avg_years,
                           notes=series.get_notes(db, ctx, fy))
    org = db.get(Workspace, ctx.workspace_id).name
    kind = "FUNDRAISER_FY_PRESENTATION" if format == "pptx" else "FUNDRAISER_FY_SUMMARY"
    summary = {"report": kind, "fiscal_year_id": fy.id, "fundraiser_ids": rep["selected_ids"],
               "options": {"years": years, "targeted": targeted, "avg_years": avg_years}, "format": format.upper()}
    if format == "json":
        db.rollback()
        return rep
    if format == "pptx":
        data = fyrep.build_pptx(org, rep)
        audit.record(db, ctx, "REPORT_GENERATED", "fiscal_year", fy.id, None, summary)
        db.commit()
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        headers={"Content-Disposition": f'attachment; filename="{fyrep.file_stem(org, rep)}-presentation.pptx"',
                                 "Cache-Control": "private, no-store"})
    path, fname, pages = fyrep.pdf_file(org, rep)
    audit.record(db, ctx, "REPORT_GENERATED", "fiscal_year", fy.id, None, {**summary, "pages": pages})
    db.commit()
    headers = {"Content-Disposition": f'{"attachment" if download else "inline"}; filename="{fname}"',
               "Cache-Control": "private, no-store", "X-Frame-Options": "SAMEORIGIN",
               "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'"}
    return FileResponse(path, media_type="application/pdf", headers=headers,
                        background=BackgroundTask(lambda: os.path.exists(path) and os.unlink(path)))


@router.get("/fundraiser-series")
def series_list(db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    return series.series_list(db, ctx)


@router.get("/fundraiser-series/start-options")
def series_start_options(db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    """2.1.0 (#292): fundraisers in no series, for "Start a series"."""
    return series.start_options(db, ctx)


@router.post("/fundraisers/{fid}/series")
def start_series(fid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    """2.1.0 (#292): the fundraiser's series, created when it has none, so prior years can be entered."""
    s = series.start_series(db, ctx, svc.get(db, ctx, fid))
    db.commit()
    return {"series_id": s.id, "series": series.series_list(db, ctx)}


@router.patch("/fundraiser-series/{sid}")
def update_series(sid: int, body: FundraiserSeriesIn, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    series.update_series(db, ctx, series._series(db, ctx, sid), body.name, body.group_as_other)
    db.commit()
    return series.series_list(db, ctx)


@router.post("/fundraiser-series/{sid}/results", status_code=201)
def add_result(sid: int, body: FundraiserSeriesResultIn, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    series.add_result(db, ctx, series._series(db, ctx, sid), body)
    db.commit()
    return series.series_list(db, ctx)


@router.post("/fundraiser-series/{sid}/results/{rid}/retire")
def retire_result(sid: int, rid: int, body: ReasonIn, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    series.retire_result(db, ctx, series._series(db, ctx, sid), rid, body.reason)
    db.commit()
    return series.series_list(db, ctx)


@router.post("/fundraiser-series/{sid}/merge")
def merge_series(sid: int, body: FundraiserSeriesMergeIn, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    series.merge(db, ctx, series._series(db, ctx, sid), series._series(db, ctx, body.into_series_id))
    db.commit()
    return series.series_list(db, ctx)


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


@router.put("/fundraisers/{fid}/buckets/order")
def order_buckets(fid: int, body: FundraiserOrderIn, db: Session = Depends(get_db), ctx: Ctx = Depends(line_manager)):
    """2.1.0 (#278): the display order of the buckets (presentation only; allowed in a closed year)."""
    f = svc.get(db, ctx, fid)
    svc.reorder(db, ctx, f, "buckets", body.ids)
    db.commit()
    return svc.detail(db, ctx, f)


# 2.1.0 (#278): bucket categories (presentation only, so they can change in a closed year too)
@router.post("/fundraisers/{fid}/categories", status_code=201)
def create_category(fid: int, body: FundraiserCategoryIn, db: Session = Depends(get_db), ctx: Ctx = Depends(line_manager)):
    f = svc.get(db, ctx, fid)
    svc.create_category(db, ctx, f, body)
    db.commit()
    return svc.detail(db, ctx, f)


@router.put("/fundraisers/{fid}/categories/order")
def order_categories(fid: int, body: FundraiserOrderIn, db: Session = Depends(get_db), ctx: Ctx = Depends(line_manager)):
    f = svc.get(db, ctx, fid)
    svc.reorder(db, ctx, f, "categories", body.ids)
    db.commit()
    return svc.detail(db, ctx, f)


@router.put("/fundraisers/{fid}/categories/{category_id}")
def update_category(fid: int, category_id: int, body: FundraiserCategoryIn, db: Session = Depends(get_db),
                    ctx: Ctx = Depends(line_manager)):
    f = svc.get(db, ctx, fid)
    svc.update_category(db, ctx, f, svc.get_category(db, f, category_id), body)
    db.commit()
    return svc.detail(db, ctx, f)


@router.delete("/fundraisers/{fid}/categories/{category_id}")
def delete_category(fid: int, category_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(line_manager)):
    f = svc.get(db, ctx, fid)
    svc.delete_category(db, ctx, f, svc.get_category(db, f, category_id))
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


# ------------------------------------------------------------------ 2.1.0 (#275): stakeholder report
@router.get("/fundraisers/{fid}/summary-report")
def summary_report(fid: int, format: Literal["pdf", "docx"] = "pdf", itemized: bool = True, names: bool = True,
                   plain_lines: bool = False, download: bool = False, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(viewer)):
    """The Financial & Proceeds Statement for committee and stakeholders (no audit detail)."""
    f = svc.get(db, ctx, fid)
    s = fs.summary(db, ctx, f, itemized=itemized, names=names, plain_lines=plain_lines)
    opts = {"itemized": itemized, "names": names, "plain_lines": plain_lines}
    if format == "docx":
        data = fs.build_docx(s)
        audit.record(db, ctx, "REPORT_GENERATED", "fundraiser", f.id, None,
                     {"report": "FUNDRAISER_SUMMARY", "format": "DOCX", "options": opts})
        db.commit()
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="{fs.docx_name(s)}"',
                                 "Cache-Control": "private, no-store"})
    path, fname, pages = fs.pdf_file(db, ctx, s)
    audit.record(db, ctx, "REPORT_GENERATED", "fundraiser", f.id, None,
                 {"report": "FUNDRAISER_SUMMARY", "format": "PDF", "options": opts, "pages": pages})
    db.commit()
    headers = {"Content-Disposition": f'{"attachment" if download else "inline"}; filename="{fname}"',
               "Cache-Control": "private, no-store", "X-Frame-Options": "SAMEORIGIN",
               "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'"}
    return FileResponse(path, media_type="application/pdf", headers=headers,
                        background=BackgroundTask(lambda: os.path.exists(path) and os.unlink(path)))


@router.get("/fundraisers/{fid}/presentation")
def presentation(fid: int, itemized: bool = True, names: bool = True, db: Session = Depends(get_db),
                 ctx: Ctx = Depends(viewer)):
    """2.1.0 (#276): the stakeholder report as a 16:9 .pptx (PowerPoint, Google Slides, Keynote); always downloaded."""
    f = svc.get(db, ctx, fid)
    s = fs.summary(db, ctx, f, itemized=itemized, names=names)
    data = deck.build(s)
    audit.record(db, ctx, "REPORT_GENERATED", "fundraiser", f.id, None,
                 {"report": "FUNDRAISER_PRESENTATION", "format": "PPTX", "options": {"itemized": itemized, "names": names}})
    db.commit()
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    headers={"Content-Disposition": f'attachment; filename="{deck.file_name(s)}"',
                             "Cache-Control": "private, no-store"})


@router.put("/fundraisers/{fid}/summary-notes")
def summary_notes(fid: int, body: FundraiserNotesIn, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    f = svc.set_summary_notes(db, ctx, svc.get(db, ctx, fid), body.summary_notes)
    db.commit()
    return svc.detail(db, ctx, f)


@router.put("/fundraisers/{fid}/results-final")
def results_final(fid: int, body: FundraiserFinalIn, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    f = svc.set_results_final(db, ctx, svc.get(db, ctx, fid), body.final)
    db.commit()
    return svc.detail(db, ctx, f)


@router.put("/fundraisers/{fid}/series-link")
def series_link(fid: int, body: FundraiserLinkIn, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    """2.1.0 (#277): change or remove "Continues from" - allowed in any Fiscal Year (reporting only)."""
    f = series.set_link(db, ctx, svc.get(db, ctx, fid), body.continues_from_id)
    db.commit()
    return svc.detail(db, ctx, f)


@router.get("/fundraisers/{fid}/next-year")
def next_year(fid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(manager)):
    """2.1.0 (#277): pre-filled values for "Create next year's from this one"."""
    return series.next_year_draft(db, ctx, svc.get(db, ctx, fid))
