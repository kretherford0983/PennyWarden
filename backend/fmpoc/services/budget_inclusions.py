"""2.3.0 (#414): years a budget's money was **included in another budget**.

Decided with Kyle 2026-10-30: a Budget Manager marks, on a budget's History, a year in which the budget had no figures
of its own because its money was inside another budget (e.g. 100-05 Kiwanis in FY2025, inside 102 Fundraisers). The
Budget Review then shows *included in 102 Fundraisers -> 100-00 Other* in that year instead of "—".

- **Any budget of the same type** (Income/Expense), at any level: a budget from before PennyWarden for a year before
  PennyWarden, or a budget of that Fiscal Year for a year in PennyWarden (Kyle: both kinds of year).
- **Shown only on the marked budget**; the other budget's cell gets no "includes ..." note.
- **No figures**: the year isn't counted in Avg (the review cell stays empty); BR-048 reporting only.
- #415's automatic *history on parent* stays for parents without sub-budgets; a mark takes its place in that year.
- Stored on the earliest budget of the marked budget's line (like the #381 link) and found across the line, so no
  "former budget" is created for an event that never had an old-spreadsheet line.
- Never deleted (BR-001): retired with a reason; marking and retiring are audited.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, conflict, not_found, validation
from ..models import Budget, BudgetInclusion, FiscalYear, FormerBudget, utcnow
from . import budget_history as hist
from .common import budget_display_code
from .fundraiser_series import fy_year


def _code(db: Session, b: Budget) -> str:
    return budget_display_code(b, db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None)


def _line_ids(db: Session, b: Budget) -> list[int]:
    return [x.id for x in hist.line_budgets(db, b)]


def _marks(db: Session, b: Budget, retired: bool = False) -> list[BudgetInclusion]:
    if b.is_budget_zero:
        return []
    q = select(BudgetInclusion).where(BudgetInclusion.budget_id.in_(_line_ids(db, b)))
    if not retired:
        q = q.where(BudgetInclusion.retired_at.is_(None))
    return list(db.scalars(q.order_by(BudgetInclusion.year, BudgetInclusion.id)))


def target_text(db: Session, m: BudgetInclusion) -> str:
    """"102 Fundraisers -> 100-00 Other" (a budget from before PennyWarden, with the budget that continues it) or
    "100-00 Other" (a budget of that Fiscal Year)."""
    if m.included_former_budget_id:
        f = db.get(FormerBudget, m.included_former_budget_id)
        code, name = hist.current_label(db, f)
        by = hist.continued_by(db, f)
        return f"{code} {name}" + (f" → {_code(db, by)} {by.name}" if by is not None else "")
    x = db.get(Budget, m.included_budget_id)
    return f"{_code(db, x)} {x.name}"


def out(db: Session, m: BudgetInclusion, counted: bool | None = None) -> dict:
    y = db.get(FiscalYear, m.fiscal_year_id) if m.fiscal_year_id is not None else None
    return {"start_date": y.start_date.isoformat() if y is not None else None,"id": m.id, "budget_id": m.budget_id, "year": m.year, "fiscal_year_label": m.fiscal_year_label,
            "fiscal_year_id": m.fiscal_year_id, "in_pennywarden": m.fiscal_year_id is not None,
            "included_former_budget_id": m.included_former_budget_id, "included_budget_id": m.included_budget_id,
            "included_in": target_text(db, m), "text": f"included in {target_text(db, m)}", "note": m.note,
            "counted": counted, "retired": m.retired_at is not None,
            "retired_at": m.retired_at.isoformat(timespec="seconds") + "Z" if m.retired_at else None,
            "retire_reason": m.retire_reason}


def _has_own(db: Session, b: Budget, m: BudgetInclusion, first: int | None) -> bool:
    """Figures always win over a mark: a budget of the line in that Fiscal Year, or an entered figure that year."""
    if m.fiscal_year_id is not None:
        return any(x.fiscal_year_id == m.fiscal_year_id for x in hist.line_budgets(db, b) if x.status != "DELETED")
    return m.year in hist.figures(db, b, first)


def notes_for(db: Session, b: Budget, first: int | None) -> dict[tuple, str]:
    """For the Budget Review: ("fy", fiscal_year_id) / ("entered", year) -> "included in ..." (active marks)."""
    res: dict[tuple, str] = {}
    for m in _marks(db, b):
        key = ("fy", m.fiscal_year_id) if m.fiscal_year_id is not None else ("entered", m.year)
        res.setdefault(key, f"included in {target_text(db, m)}")
    return res


def for_view(db: Session, b: Budget, first: int | None) -> list[dict]:
    return [out(db, m, counted=m.retired_at is None and not _has_own(db, b, m, first))
            for m in _marks(db, b, retired=True)]


def _check(b: Budget) -> None:
    if b.is_budget_zero or b.status == "DELETED":
        raise validation("Budget 0 and deleted budgets have no history to mark.", "budget_id")


def options(db: Session, ctx, b: Budget) -> dict:
    """What a year can be marked as included in: the earlier Fiscal Years in PennyWarden without a budget of this line
    (each with its budgets of the same type), and the budgets from before PennyWarden of the same type."""
    _check(b)
    fy = db.get(FiscalYear, b.fiscal_year_id)
    line_fys = {x.fiscal_year_id for x in hist.line_budgets(db, b)}
    line_ids = set(_line_ids(db, b))
    years = []
    for y in db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ctx.workspace_id,
                                                 FiscalYear.start_date < fy.start_date)
                        .order_by(FiscalYear.start_date.desc())):
        if y.id in line_fys:
            continue
        budgets = [x for x in db.scalars(select(Budget).where(Budget.fiscal_year_id == y.id,
                                                              Budget.budget_type == b.budget_type,
                                                              Budget.status != "DELETED",
                                                              Budget.is_budget_zero.is_(False)))
                   if x.id not in line_ids]
        if budgets:
            rows = sorted(({"id": x.id, "code": _code(db, x), "name": x.name} for x in budgets),
                          key=lambda r: hist._sort_code(r["code"]))
            years.append({"id": y.id, "display_name": y.display_name,
                          "budgets": [{**r, "label": f"{r['code']} {r['name']}"} for r in rows]})
    own = hist.former_of(db, b)
    formers = []
    for f in db.scalars(select(FormerBudget).where(FormerBudget.workspace_id == ctx.workspace_id,
                                                   FormerBudget.budget_type == b.budget_type,
                                                   FormerBudget.retired_at.is_(None))):
        if own is not None and f.id == own.id:
            continue
        code, name = hist.current_label(db, f)
        by = hist.continued_by(db, f)
        formers.append({"id": f.id, "code": code, "name": name,
                        "label": f"{code} {name}" + (f" → {_code(db, by)} {by.name}" if by is not None else "")})
    formers.sort(key=lambda r: hist._sort_code(r["code"]))
    return {"first_year": hist.first_year(db, ctx.workspace_id), "fiscal_years": years, "formers": formers}


def mark(db: Session, ctx, b: Budget, body) -> BudgetInclusion:
    """Mark a year of b's line as included in another budget (exactly one of a Fiscal Year in PennyWarden with a
    budget of it, or a label before PennyWarden with a budget from before PennyWarden)."""
    _check(b)
    fy = db.get(FiscalYear, b.fiscal_year_id)
    line = hist.line_budgets(db, b)
    holder = line[-1]
    first = hist.first_year(db, ctx.workspace_id)
    note = hist._clean(body.note, 500)
    if body.fiscal_year_id is not None:
        if body.fiscal_year_label or body.included_former_budget_id is not None:
            raise validation("A year in PennyWarden is included in a budget of that Fiscal Year.", "fiscal_year_id")
        y = db.get(FiscalYear, body.fiscal_year_id)
        if y is None or y.workspace_id != ctx.workspace_id:
            raise not_found("Fiscal Year")
        if y.start_date >= fy.start_date:
            raise validation("Choose a Fiscal Year before this budget's.", "fiscal_year_id")
        if any(x.fiscal_year_id == y.id for x in line):
            raise AppError(409, "HAS_FIGURES", f"{y.display_name}: this budget's line has a budget that year.")
        x = db.get(Budget, body.included_budget_id) if body.included_budget_id is not None else None
        if x is None or x.workspace_id != ctx.workspace_id:
            raise validation("Choose the budget its money was included in.", "included_budget_id")
        if x.fiscal_year_id != y.id or x.is_budget_zero or x.status == "DELETED":
            raise validation(f"Choose a budget of {y.display_name} (not Budget 0).", "included_budget_id")
        if x.id in {z.id for z in line}:
            raise validation("A budget can't be included in its own line.", "included_budget_id")
        if x.budget_type != b.budget_type:
            raise validation("Choose a budget of the same type (Income or Expense).", "included_budget_id")
        m = BudgetInclusion(workspace_id=ctx.workspace_id, budget_id=holder.id, year=fy_year(y),
                            fiscal_year_label=y.display_name, fiscal_year_id=y.id, included_budget_id=x.id,
                            note=note, created_by_user_id=ctx.user.id)
        dup = BudgetInclusion.fiscal_year_id == y.id
    else:
        if body.included_budget_id is not None:
            raise validation("A year before PennyWarden is included in a budget from before PennyWarden.",
                             "included_former_budget_id")
        label = (body.fiscal_year_label or "").strip()
        if not label:
            raise validation("Choose the year.", "fiscal_year_label")
        year = hist._year_of(db, ctx.workspace_id, label)
        if year >= fy_year(fy):
            raise validation("Choose a year before this budget's Fiscal Year.", "fiscal_year_label")
        if year in hist.figures(db, b, first):
            raise AppError(409, "HAS_FIGURES", f"{label}: figures are entered for that year on this budget's line.")
        f = db.get(FormerBudget, body.included_former_budget_id) if body.included_former_budget_id is not None else None
        if f is None or f.workspace_id != ctx.workspace_id or f.retired_at is not None:
            raise validation("Choose the budget from before PennyWarden its money was included in.",
                             "included_former_budget_id")
        own = hist.former_of(db, b)
        if own is not None and own.id == f.id:
            raise validation("A budget can't be included in its own line.", "included_former_budget_id")
        if f.budget_type != b.budget_type:
            raise validation("Choose a budget of the same type (Income or Expense).", "included_former_budget_id")
        m = BudgetInclusion(workspace_id=ctx.workspace_id, budget_id=holder.id, year=year, fiscal_year_label=label,
                            included_former_budget_id=f.id, note=note, created_by_user_id=ctx.user.id)
        dup = (BudgetInclusion.fiscal_year_id.is_(None)) & (BudgetInclusion.year == year)
    if db.scalar(select(BudgetInclusion.id).where(BudgetInclusion.budget_id.in_([z.id for z in line]),
                                                  BudgetInclusion.retired_at.is_(None), dup).limit(1)):
        raise AppError(409, "YEAR_MARKED", f"{m.fiscal_year_label} is already marked on this budget's line; retire "
                       "that mark first.")
    db.add(m)
    db.flush()
    audit.record(db, ctx, "BUDGET_HISTORY_INCLUSION_MARKED", "budget", holder.id, None,
                 {**out(db, m), "marked_on_budget_id": b.id})
    return m


def retire(db: Session, ctx, mark_id: int, reason: str) -> BudgetInclusion:
    m = db.get(BudgetInclusion, mark_id) if isinstance(mark_id, int) else None
    if m is None or m.workspace_id != ctx.workspace_id:
        raise not_found("Included-in mark")
    if m.retired_at is not None:
        raise conflict("ALREADY_RETIRED", "This mark is already retired.")
    before = out(db, m)
    m.retired_at, m.retired_by_user_id, m.retire_reason = utcnow(), ctx.user.id, reason.strip()
    db.flush()
    audit.record(db, ctx, "BUDGET_HISTORY_INCLUSION_RETIRED", "budget", m.budget_id, before, out(db, m))
    return m
