from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..errors import forbidden
from ..deps import Ctx, auth_ctx, get_db, require
from ..models import FiscalYear
from ..services import charts as charts_svc
from ..services.common import get_scoped
from ..services import dashboard as svc

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)):
    if ctx.user.security_domain == "ADMINISTRATOR":
        return svc.administrator(db, ctx)
    if ctx.user.security_domain == "AUDITOR":
        return svc.auditor(db, ctx)
    if ctx.user.security_domain == "COMBINED":   # 1.9.0 (#54): one person with roles of several domains
        if "AUDITOR" in ctx.roles:
            return svc.auditor(db, ctx)             # the financial dashboard plus the Auditor's review summary
        if ctx.has("financial.view"):
            return svc.financial(db, ctx)
        return svc.administrator(db, ctx)
    if not ctx.has("financial.view"):      # 2.4.0 (#251): an Invoice Manager alone has no Dashboard (budget figures)
        raise forbidden()
    return svc.financial(db, ctx)


@router.get("/dashboard/charts")
def dashboard_charts(fiscal_year_id: int = Query(...), db: Session = Depends(get_db),
                     ctx: Ctx = Depends(require("financial.view"))):
    """v1.4.1 CR-020: chart data for one Fiscal Year (financial roles and Auditors)."""
    return charts_svc.data(db, ctx, get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year"))
