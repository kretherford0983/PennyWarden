"""Shared helpers for financial services."""
from __future__ import annotations

import calendar
import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import not_found
from ..money import fmt
from ..models import Budget, Entity, FiscalYear, RegisterTransaction, TransactionAllocation

# 2.3.0 (#371, BR-109): budgets are gross. The same sentence is GROSS_BUDGET_NOTE in frontend/src/components.tsx
# (a test keeps the two identical); every screen, report and deck that shows budget amounts carries it.
GROSS_BUDGET_NOTE = ("Budget amounts are gross. Offsetting income or expense recorded in a budget of the opposite "
                     "type, such as a reimbursement, is not subtracted.")


def get_scoped(db: Session, model, obj_id: int, ctx, what: str | None = None):
    """Object-level authorization: records are only reachable inside the caller's workspace (BR-099)."""
    obj = db.get(model, obj_id) if isinstance(obj_id, int) else None
    if obj is None or getattr(obj, "workspace_id", ctx.workspace_id) != ctx.workspace_id:
        raise not_found(what or model.__name__)
    return obj


def add_months(d: dt.date, months: int) -> dt.date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def quarters(fy: FiscalYear) -> list[tuple[str, dt.date, dt.date]]:
    """BR-009: four consecutive three-month periods starting at the Fiscal Year start date.
    Q4 extends to the Fiscal Year end date."""
    out = []
    for i in range(4):
        start = add_months(fy.start_date, 3 * i)
        end = fy.end_date if i == 3 else add_months(fy.start_date, 3 * (i + 1)) - dt.timedelta(days=1)
        out.append((f"Q{i + 1}", start, min(end, fy.end_date) if i < 3 else end))
    return out


def fy_label(fy: FiscalYear) -> str:
    """BR-FY-VIS-003: identity first, status as an optional suffix."""
    return f"{fy.display_name} — {fy.status.title()}"


def fy_brief(fy: FiscalYear | None) -> dict | None:
    if fy is None:
        return None
    return {"id": fy.id, "display_name": fy.display_name, "status": fy.status, "label": fy_label(fy),
            "start_date": fy.start_date.isoformat(), "end_date": fy.end_date.isoformat()}


def covering_fiscal_years(db: Session, ws_id: int, d: dt.date) -> list[FiscalYear]:
    return list(db.scalars(select(FiscalYear).where(
        FiscalYear.workspace_id == ws_id, FiscalYear.start_date <= d, FiscalYear.end_date >= d
    ).order_by(FiscalYear.start_date)))


def closest_fiscal_year(db: Session, ws_id: int, d: dt.date) -> FiscalYear | None:
    fys = list(db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id)))
    if not fys:
        return None

    def dist(fy):
        if d < fy.start_date:
            return (fy.start_date - d).days
        if d > fy.end_date:
            return (d - fy.end_date).days
        return 0

    return min(fys, key=lambda f: (dist(f), f.start_date))


def entity_brief(e: Entity | None) -> dict | None:
    if e is None:
        return None
    return {"id": e.id, "entity_number": e.entity_number, "display_name": e.display_name,
            "entity_type": e.entity_type, "active": e.active, "is_system": e.is_system,
            "is_financial_institution": e.is_financial_institution}


def active_allocation_totals(db: Session, budget_ids: list[int] | None = None,
                             date_from: dt.date | None = None, date_to: dt.date | None = None) -> dict[int, int]:
    """Sum of ACTIVE (non-void) live allocations per budget (BR-048)."""
    q = (select(TransactionAllocation.budget_id, func.coalesce(func.sum(TransactionAllocation.amount_cents), 0))
         .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
         .where(RegisterTransaction.status == "ACTIVE", TransactionAllocation.removed_at.is_(None)))
    if budget_ids is not None:
        q = q.where(TransactionAllocation.budget_id.in_(budget_ids))
    if date_from is not None:
        q = q.where(RegisterTransaction.transaction_date >= date_from)
    if date_to is not None:
        q = q.where(RegisterTransaction.transaction_date <= date_to)
    return {bid: int(total) for bid, total in db.execute(q.group_by(TransactionAllocation.budget_id))}


def budget_display_code(b: Budget, parent: Budget | None) -> str:
    if b.parent_budget_id is None or parent is None:
        return b.parent_code
    return f"{parent.parent_code}-{b.child_code}"


def budget_label(b: Budget, parent: Budget | None) -> str:
    return f"{budget_display_code(b, parent)} {b.name}"


__all__ = ["fmt"]
