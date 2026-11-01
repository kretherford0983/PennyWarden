"""v1.2 reporting endpoints (CR-002). Read-only for all financial roles and Auditors; generation is audited."""
from __future__ import annotations

import datetime as dt
import os
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from .. import audit
from ..deps import Ctx, get_db, require
from ..models import FiscalYear, Workspace
from ..schemas import FlowReportIn, FlowReportPdfIn, ProjectionChoicesIn, SignatureTemplateIn
from ..services import budget_planning as plan
from ..services import flow_report as flow
from ..services import reports as svc
from ..services import signatures as sig
from ..services.common import get_scoped

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _disposition(kind: str, name: str) -> str:
    ascii_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


@router.get("/signature-templates")
def signature_templates(db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    """v1.4.1 CR-016: built-in default wording + the organization's saved wordings (max 4)."""
    return sig.list_templates(db, ctx.workspace_id)


@router.post("/signature-templates", status_code=201)
def save_signature_template(body: SignatureTemplateIn, db: Session = Depends(get_db),
                            ctx: Ctx = Depends(require("financial.view"))):
    return sig.save_template(db, ctx, body.text)


@router.delete("/signature-templates/{template_id}")
def delete_signature_template(template_id: int, db: Session = Depends(get_db),
                              ctx: Ctx = Depends(require("financial.view"))):
    sig.delete_template(db, ctx, template_id)
    return {"ok": True}


@router.get("/audit/signature-page")
def signature_page_preview(request: Request, fiscal_year_id: int = Query(...),
                           signature_template_id: str | None = Query(None, max_length=20),
                           signature_text: str | None = Query(None, max_length=sig.MAX_TEXT + 500),
                           signer_id: list[int] = Query([]), signer_title: list[str] = Query([]),
                           db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    """v1.5.0 CR-029: preview/print the signature page without generating the whole audit report."""
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
    signature = sig.resolve(db, ctx, fy, db.get(Workspace, ctx.workspace_id), signature_template_id, signature_text,
                            signer_id, signer_title)
    path, fname = svc.build_signature_page(db, ctx, fy, signature)
    audit.record(db, ctx, "REPORT_GENERATED", "fiscal_year", fy.id, None,
                 {"report": "SIGNATURE_PAGE", "wording": signature.source, "signers": len(signature.signers)})
    db.commit()
    headers = {"Content-Disposition": _disposition("inline", fname), "Cache-Control": "private, no-store",
               "X-Frame-Options": "SAMEORIGIN", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'"}
    return FileResponse(path, media_type="application/pdf", headers=headers,
                        background=BackgroundTask(lambda: os.path.exists(path) and os.unlink(path)))


@router.get("/audit")
def audit_report(request: Request, fiscal_year_id: int = Query(...), bank_account_id: int | None = None,
                 include_void: bool = True, download: bool = False,
                 signature_page: bool = False, signature_template_id: str | None = Query(None, max_length=20),
                 signature_text: str | None = Query(None, max_length=sig.MAX_TEXT + 500),
                 signer_id: list[int] = Query([]), signer_title: list[str] = Query([]),
                 include_fundraisers: bool = False,
                 db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
    signature = None
    if signature_page:  # v1.4.1 CR-016
        signature = sig.resolve(db, ctx, fy, db.get(Workspace, ctx.workspace_id), signature_template_id,
                                signature_text, signer_id, signer_title)
    path, fname, summary = svc.build_audit_report(db, ctx, request.app.state.settings, fy, bank_account_id, include_void,
                                                  signature=signature, fundraisers=include_fundraisers)
    extra = ({"signature_page": {"wording": signature.source, "signers": len(signature.signers)}}
             if signature else {})
    audit.record(db, ctx, "REPORT_GENERATED", "fiscal_year", fy.id, None,
                 {"report": "END_OF_YEAR_AUDIT", "bank_account_id": bank_account_id, "include_void": include_void,
                  **summary, **extra})
    db.commit()
    headers = {"Content-Disposition": _disposition("attachment" if download else "inline", fname),
               "Cache-Control": "private, no-store", "X-Frame-Options": "SAMEORIGIN",
               "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'"}
    return FileResponse(path, media_type="application/pdf", headers=headers,
                        background=BackgroundTask(lambda: os.path.exists(path) and os.unlink(path)))


@router.get("/fy-close")
def close_report(request: Request, fiscal_year_id: int = Query(...), download: bool = False,
                 include_fundraisers: bool = True,
                 db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    """v1.3 CR-008: Fiscal Year Close report (all accounts, VOID included, Fiscal Year documents up front)."""
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
    path, fname, summary = svc.build_audit_report(db, ctx, request.app.state.settings, fy, None, True, layout="close",
                                                  fundraisers=include_fundraisers)
    audit.record(db, ctx, "REPORT_GENERATED", "fiscal_year", fy.id, None, {"report": "FISCAL_YEAR_CLOSE", **summary})
    db.commit()
    headers = {"Content-Disposition": _disposition("attachment" if download else "inline", fname),
               "Cache-Control": "private, no-store", "X-Frame-Options": "SAMEORIGIN",
               "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'"}
    return FileResponse(path, media_type="application/pdf", headers=headers,
                        background=BackgroundTask(lambda: os.path.exists(path) and os.unlink(path)))


@router.get("/entity-activity")
def entity_activity(bank_account_id: int | None = None, fiscal_year_id: int | None = None,
                    date_from: dt.date | None = None, date_to: dt.date | None = None, entity_id: int | None = None,
                    details: bool = False, format: Literal["json", "csv"] = "json",
                    db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    if fiscal_year_id is not None:
        fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
        date_from, date_to = date_from or fy.start_date, date_to or fy.end_date
    if date_from is None or date_to is None:
        from ..errors import validation
        raise validation("Provide date_from and date_to, or a fiscal_year_id.", "date_from")
    report = svc.entity_activity(db, ctx, account_id=bank_account_id, date_from=date_from, date_to=date_to,
                                 entity_id=entity_id, include_details=details or format == "csv")
    audit.record(db, ctx, "REPORT_GENERATED", "bank_account" if bank_account_id else "workspace",
                 bank_account_id or ctx.workspace_id, None,
                 {"report": "ENTITY_ACTIVITY", "date_from": date_from, "date_to": date_to, "entity_id": entity_id,
                  "format": format})
    db.commit()
    if format == "csv":
        name = f"entity-activity-{date_from}-to-{date_to}.csv"
        return Response(svc.entity_activity_csv(report), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": _disposition("attachment", name)})
    return report


# ------------------------------------------------------------------ 1.8.0 (#106) Financial Flow Report
@router.post("/financial-flow/review")
def flow_review(body: FlowReportIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    """The lines the report would list, for the review form (read-only; not audited - nothing is produced)."""
    return flow.preview(db, ctx, body)


@router.post("/financial-flow")
def flow_pdf(body: FlowReportPdfIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    """The PDF from the reviewed lines. The audit entry records the parameters, the line notes and every excluded
    line with its reason; neither the exclusions nor the reasons are printed."""
    path, fname, summary = flow.build_pdf(db, ctx, body)
    audit.record(db, ctx, "REPORT_GENERATED", "workspace", ctx.workspace_id, None, summary)
    db.commit()
    headers = {"Content-Disposition": _disposition("attachment" if body.download else "inline", fname),
               "Cache-Control": "private, no-store", "X-Frame-Options": "SAMEORIGIN",
               "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'"}
    return FileResponse(path, media_type="application/pdf", headers=headers,
                        background=BackgroundTask(lambda: os.path.exists(path) and os.unlink(path)))


# ------------------------------------------------------------------ 2.1.0 (#257, #261) budget planning (Budget Managers)
def _pdf_response(path: str, fname: str, download: bool) -> FileResponse:
    headers = {"Content-Disposition": _disposition("attachment" if download else "inline", fname),
               "Cache-Control": "private, no-store", "X-Frame-Options": "SAMEORIGIN",
               "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'"}
    return FileResponse(path, media_type="application/pdf", headers=headers,
                        background=BackgroundTask(lambda: os.path.exists(path) and os.unlink(path)))


@router.get("/budget-review/projection-choices")
@router.get("/budget-prep/projection-choices", include_in_schema=False)       # 2.1.0 (#283): the old path still works
def projection_choices(fiscal_year_id: int = Query(...), db: Session = Depends(get_db),
                       ctx: Ctx = Depends(require("budget.manage"))):
    """The budgets the person can project or leave unprojected, with their remembered choice (or the default)."""
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
    return plan.choices_view(db, ctx, fy)


@router.put("/budget-review/projection-choices")
@router.put("/budget-prep/projection-choices", include_in_schema=False)
def save_projection_choices(body: ProjectionChoicesIn, db: Session = Depends(get_db),
                            ctx: Ctx = Depends(require("budget.manage"))):
    fy = get_scoped(db, FiscalYear, body.fiscal_year_id, ctx, "Fiscal Year")
    out = plan.save_choices(db, ctx, fy, body.choices, body.reset)
    db.commit()
    return out


@router.get("/budget-review")
@router.get("/budget-prep", include_in_schema=False)
def budget_review(fiscal_year_id: int = Query(...), years: int = Query(3, ge=0, le=plan.REVIEW_MAX_YEARS),
                projected: bool = False, include_next: bool = False, budget_id: int | None = None,
                parent_budget_id: int | None = None, as_of: dt.date | None = None,
                format: Literal["json", "pdf", "csv"] = "json", download: bool = False,
                paper: Literal["LETTER", "LEGAL"] = "LETTER",
                db: Session = Depends(get_db), ctx: Ctx = Depends(require("budget.manage"))):
    """#257 Budget Review report (named Budget Prep until #283): each budget of the year with its linked history and
    averages, YTD actuals and (optionally) the projection and the next year's continuing budget. 2.3.0 polish: 0 to 9
    prior years (the most a one-page legal PDF holds; "every linked year", years=-1, is gone)."""
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
    rep = plan.budget_review(db, ctx, fy, years=years, projected=projected, include_next=include_next,
                             budget_id=budget_id, parent_budget_id=parent_budget_id, as_of=as_of)
    summary = {"report": "BUDGET_REVIEW", "format": format, "years": len(rep["years"]), "as_of": rep["as_of"],
               "projected": projected, "include_next": include_next, "budget_id": budget_id,
               "parent_budget_id": parent_budget_id}
    if projected:
        summary["not_projected"] = [r["id"] for s in ("income", "expense") for r in rep[s]
                                    if (r["projection"] or {}).get("state") == "NOT_PROJECTED"]
    if format == "pdf":
        plan.check_pdf_fits(rep, paper)           # 2.3.0 polish: every column on one page
        path, fname, pages = plan.budget_review_pdf(db, ctx, rep, paper)
        summary["pages"], summary["paper"] = pages, paper
    audit.record(db, ctx, "REPORT_GENERATED", "fiscal_year", fy.id, None, summary)
    db.commit()
    if format == "pdf":
        return _pdf_response(path, fname, download)
    if format == "csv":
        return Response(plan.budget_review_csv(rep), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": _disposition("attachment", f"budget-review-{plan._safe(fy.display_name)}.csv"),
                                 "Cache-Control": "private, no-store"})
    return rep


@router.get("/planning-sheet/context")
def planning_sheet_context(db: Session = Depends(get_db), ctx: Ctx = Depends(require("budget.manage"))):
    """Which year the sheet lists and which Draft year (if any) fills the Proposed column."""
    return plan.planning_context_out(db, ctx.workspace_id)


@router.get("/planning-sheet")
def planning_sheet(fiscal_year_id: int | None = None, as_of: dt.date | None = None, download: bool = False,
                   include_review: bool = False, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("budget.manage"))):
    """#261 Fiscal Year Planning Sheet: the printed form for the budget planning meeting. Without fiscal_year_id
    (the Fiscal Years page) the year being planned is worked out: a Draft year and the year before it, else the
    current year."""
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year") if fiscal_year_id is not None else None
    path, fname, summary = plan.planning_sheet(db, ctx, fy, as_of)
    if include_review:      # 2.1.0 (#283): the Budget Review pages after the sheet, in one PDF
        path, summary = plan.append_review(db, ctx, path, summary, as_of)
    audit.record(db, ctx, "REPORT_GENERATED", "fiscal_year", summary["fiscal_year_id"], None, summary)
    db.commit()
    return _pdf_response(path, fname, download)


# ------------------------------------------------------------------ 2.3.0 (#373) Quarterly / Annual FY report
def _today() -> dt.date:
    """Computed when the request runs (never at import), so a run that crosses midnight uses the right day."""
    return dt.date.today()


@router.get("/period/options")
def period_options(fiscal_year_id: int = Query(...), db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("financial.view"))):
    from ..services import period_report as prep
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
    prior = prep.previous_fy(db, fy)
    return {"periods": prep.options(fy, _today()), "prior_fiscal_year": prior.display_name if prior else None,
            "max_commentary": prep.MAX_COMMENTARY}


@router.get("/period")
def period_report(fiscal_year_id: int = Query(...), period: Literal["Q1", "Q2", "Q3", "Q4", "ANNUAL"] = Query(...),
                  commentary: str | None = Query(None, max_length=2000),
                  format: Literal["json", "pdf", "pptx"] = "pdf", download: bool = False,
                  db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    """The Quarterly or Annual Fiscal Year financial report (PDF) or presentation (.pptx), as of the end of the
    period (BR-110). Generation is audited with its parameters."""
    from ..services import branding
    from ..services import period_report as prep
    from ..services import period_report_output as out
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
    rep = prep.build(db, ctx, fy, period, _today(), commentary)
    if format == "json":
        db.rollback()
        return rep
    org = db.get(Workspace, ctx.workspace_id).name
    summary = {"report": "FY_PERIOD_PRESENTATION" if format == "pptx" else "FY_PERIOD_REPORT",
               "fiscal_year_id": fy.id, "period": period, "cutoff": rep["cutoff"], "preliminary": rep["preliminary"],
               "commentary": bool(rep["commentary"]), "format": format.upper()}
    if format == "pptx":
        with branding.use(db, output="presentations"):
            data = out.build_pptx(org, rep)
        audit.record(db, ctx, "REPORT_GENERATED", "fiscal_year", fy.id, None, summary)
        db.commit()
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        headers={"Content-Disposition": _disposition("attachment", out.file_stem(org, rep) + "-presentation.pptx"),
                                 "Cache-Control": "private, no-store"})
    with branding.use(db):
        path, fname, pages = out.pdf_file(org, rep)
    audit.record(db, ctx, "REPORT_GENERATED", "fiscal_year", fy.id, None, {**summary, "pages": pages})
    db.commit()
    return _pdf_response(path, fname, download)
