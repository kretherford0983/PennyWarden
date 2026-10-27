from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..models import Budget, FiscalYear
from ..schemas import (BudgetCreateIn, BudgetHistoryCorrectIn, BudgetHistoryCsvIn, BudgetHistoryIn, BudgetUpdateIn,
                       ReasonIn)
from ..services import budget_history as hist
from ..services import budgets as svc
from ..services.common import get_scoped

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


@router.get("")
def budget_tree(fiscal_year_id: int = Query(...), db: Session = Depends(get_db),
                ctx: Ctx = Depends(require("financial.view"))):
    return svc.tree(db, get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year"),
                    include_deleted="AUDITOR" in ctx.roles)  # 1.7.3 (#52): Auditors also see deleted budgets


@router.get("/selectable")
def selectable(fiscal_year_id: int = Query(...), transaction_type: Literal["DEPOSIT", "WITHDRAWAL"] | None = None,
               db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    return svc.selectable(db, ctx.workspace_id, get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year"),
                          transaction_type)


@router.get("/filter-options")
def filter_options(fiscal_year_id: int | None = None, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("financial.view"))):
    """1.7.3 (#104): the Register's Budget filter - one Fiscal Year's budgets, or every year's."""
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year") if fiscal_year_id else None
    return svc.filter_options(db, ctx.workspace_id, fy)


@router.get("/continue-options")
def continue_options(fiscal_year_id: int = Query(...), budget_type: Literal["INCOME", "EXPENSE"] = Query(...),
                     level: Literal["budget", "sub-budget"] = "budget", budget_id: int | None = None,
                     db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    """1.8.0 (#89): budgets of earlier Fiscal Years that a budget can continue, grouped by Fiscal Year."""
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
    if budget_id is not None:
        get_scoped(db, Budget, budget_id, ctx, "Budget")
    return svc.continue_options(db, ctx.workspace_id, fy, budget_type, level == "sub-budget", budget_id)


@router.get("/{budget_id}/history")
def history(budget_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    """1.8.0 (#89): the budget's lineage across Fiscal Years, oldest first."""
    return svc.lineage(db, get_scoped(db, Budget, budget_id, ctx, "Budget"))


# ------------------------------------------------------------------ 2.2.0 (#284) history before PennyWarden
@router.get("/history-entries/template")
def history_template(fiscal_year_id: int = Query(...), db: Session = Depends(get_db),
                     ctx: Ctx = Depends(require("budget.manage"))):
    """The CSV template: the columns and one row per budget code of the Fiscal Year."""
    from fastapi.responses import Response as R
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
    return R(hist.template_csv(db, fy), media_type="text/csv",
             headers={"Content-Disposition": 'attachment; filename="budget-history-template.csv"'})


@router.post("/history-entries/preview")
def history_preview(body: BudgetHistoryCsvIn, db: Session = Depends(get_db),
                    ctx: Ctx = Depends(require("budget.manage"))):
    """What a CSV import would do, row by row; saves nothing."""
    return hist.preview(db, ctx, get_scoped(db, FiscalYear, body.fiscal_year_id, ctx, "Fiscal Year"), body.csv)


@router.post("/history-entries/import")
def history_import(body: BudgetHistoryCsvIn, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("budget.manage"))):
    out = hist.import_csv(db, ctx, get_scoped(db, FiscalYear, body.fiscal_year_id, ctx, "Fiscal Year"), body.csv)
    db.commit()
    return out


@router.patch("/history-entries/{entry_id}")
def history_correct(entry_id: int, body: BudgetHistoryCorrectIn, db: Session = Depends(get_db),
                    ctx: Ctx = Depends(require("budget.manage"))):
    e = hist.correct(db, ctx, entry_id, body)
    db.commit()
    return hist.entry_out(e)


@router.post("/history-entries/{entry_id}/retire")
def history_retire(entry_id: int, body: ReasonIn, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("budget.manage"))):
    e = hist.retire(db, ctx, entry_id, body.reason)
    db.commit()
    return hist.entry_out(e)


@router.get("/{budget_id}/history/entered")
def history_entered(budget_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    """The years before PennyWarden entered for this budget's line (Entered), for its History view."""
    return hist.view(db, ctx, get_scoped(db, Budget, budget_id, ctx, "Budget"))


@router.post("/{budget_id}/history/entered", status_code=201)
def history_add(budget_id: int, body: BudgetHistoryIn, db: Session = Depends(get_db),
                ctx: Ctx = Depends(require("budget.manage"))):
    b = get_scoped(db, Budget, budget_id, ctx, "Budget")
    e = hist.add(db, ctx, b, body.fiscal_year_label, body.budgeted, body.actual, body.note)
    db.commit()
    return hist.entry_out(e)


@router.get("/{budget_id}")
def get_budget(budget_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    b = get_scoped(db, Budget, budget_id, ctx, "Budget")
    return {**svc.snapshot(b), "state": svc.state(b)}


@router.post("", status_code=201)
def create(body: BudgetCreateIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("budget.manage"))):
    b = svc.create(db, ctx, body)
    db.commit()
    return {**svc.snapshot(b), "state": svc.state(b)}


def _mut(fn):
    def handler(budget_id: int, db: Session, ctx: Ctx, *args):
        b = fn(db, ctx, get_scoped(db, Budget, budget_id, ctx, "Budget"), *args)
        db.commit()
        return {**svc.snapshot(b), "state": svc.state(b)}
    return handler


@router.patch("/{budget_id}")
def update(budget_id: int, body: BudgetUpdateIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("budget.manage"))):
    return _mut(svc.update)(budget_id, db, ctx, body)


@router.post("/{budget_id}/delete")
def delete(budget_id: int, body: ReasonIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("budget.delete"))):
    """1.7.3 (#52): Budget Admin - status Deleted, only in a Fiscal Year that is not approved."""
    return _mut(svc.delete)(budget_id, db, ctx, body.reason)


@router.post("/{budget_id}/reject")
def reject(budget_id: int, body: ReasonIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("budget.manage"))):
    return _mut(svc.reject)(budget_id, db, ctx, body.reason)


@router.post("/{budget_id}/inactivate")
def inactivate(budget_id: int, body: ReasonIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("budget.manage"))):
    return _mut(svc.inactivate)(budget_id, db, ctx, body.reason)


@router.post("/{budget_id}/unlock")
def unlock(budget_id: int, body: ReasonIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("budget.manage"))):
    return _mut(svc.unlock)(budget_id, db, ctx, body.reason)


@router.post("/{budget_id}/lock")
def lock(budget_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("budget.manage"))):
    return _mut(svc.lock)(budget_id, db, ctx)
