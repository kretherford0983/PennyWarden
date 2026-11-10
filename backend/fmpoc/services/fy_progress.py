"""2.4.0 (#553): the Dashboard's FY Progress box (BR-DASH-FYP-001..003, decided with Kyle 2026-11-09).

- **Result so far:** the current Fiscal Year's Income actual - Expense actual (the figures of the two budget boxes beside
  it), shown as a surplus (>= 0) or a deficit.
- **Projected year end**, per type (income, expenses): this year so far + the **median** of what the up to 3 previous
  Fiscal Years did in the rest of their year (each one's total - its amount at the same number of days into the year;
  two years: their average) - "the gap carries over", so seasonal income (a January fundraiser) is handled, being
  behind stays in the projection, and a one-time event in one year is ignored. Without a previous Fiscal Year: this
  year's straight-line pace (as the Planning Sheet). Not before 3 months of the year have elapsed;
  once the year has ended it is the final result.
- **Budgeted:** the Income budget - the Expense budget (the active budgets, as in the boxes).
"""
from __future__ import annotations

import datetime as dt
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Budget, FiscalYear
from ..money import fmt, parse_amount
from .common import active_allocation_totals

MIN_MONTHS = 3
YEARS = 3          # previous Fiscal Years combined by their median (Kyle, 2026-11-09)


def today() -> dt.date:
    return dt.date.today()


def months_between(start: dt.date, stop: dt.date) -> Fraction:
    from .budget_planning import months_between as mb
    return mb(start, stop)


def previous_fys(db: Session, fy: FiscalYear, n: int = YEARS) -> list[FiscalYear]:
    """Up to ``n`` Fiscal Years that ended before this one started, the most recent first."""
    return list(db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == fy.workspace_id,
                                                   FiscalYear.end_date < fy.start_date)
                           .order_by(FiscalYear.end_date.desc()).limit(n)))


def median(values: list[int]) -> int:
    """The middle value; with an even count the average of the two middle ones (to the cent)."""
    v = sorted(values)
    m = len(v) // 2
    return v[m] if len(v) % 2 else _round(Fraction(v[m - 1] + v[m], 2))


def actuals(db: Session, fy: FiscalYear, date_to: dt.date | None = None) -> dict[str, int]:
    """Income and expense actuals of a Fiscal Year's budgets (Budget 0 and deleted budgets left out, as in the budget
    boxes), optionally only transactions dated up to ``date_to``."""
    budgets = list(db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id, Budget.status != "DELETED",
                                                   Budget.is_budget_zero.is_(False))))
    totals = active_allocation_totals(db, [b.id for b in budgets], date_to=date_to) if budgets else {}
    out = {"INCOME": 0, "EXPENSE": 0}
    for b in budgets:
        out[b.budget_type] = out.get(b.budget_type, 0) + totals.get(b.id, 0)
    return out


def _round(x: Fraction) -> int:
    n = int(abs(x) + Fraction(1, 2))
    return n if x >= 0 else -n


def _word(cents: int) -> str:
    return "surplus" if cents >= 0 else "deficit"


def progress(db: Session, fy: FiscalYear, summary: dict, as_of: dt.date | None = None) -> dict:
    """The box's figures. ``summary`` is the dashboard's budget summary (income / expense: amount, actual)."""
    as_of = as_of or today()
    inc, exp = (parse_amount(summary[k]["actual"], allow_negative=True) for k in ("income", "expense"))
    b_inc, b_exp = (parse_amount(summary[k]["amount"], allow_negative=True) for k in ("income", "expense"))
    net, budgeted = inc - exp, b_inc - b_exp
    out = {"result": fmt(net), "result_word": _word(net), "income": fmt(inc), "expense": fmt(exp),
           "budgeted": fmt(budgeted), "budgeted_word": _word(budgeted), "elapsed_months": None,
           "projection": {"state": "TOO_EARLY", "result": None, "result_word": None, "basis": None}}
    if as_of > fy.end_date:
        out["projection"] = {"state": "YEAR_ENDED", "result": fmt(net), "result_word": _word(net), "basis": None}
        return out
    elapsed = months_between(fy.start_date, as_of + dt.timedelta(days=1))   # today counts as elapsed
    out["elapsed_months"] = f"{float(elapsed):.1f}"
    if elapsed < MIN_MONTHS:
        return out
    prevs = previous_fys(db, fy)
    if prevs:
        rest: dict[str, list[int]] = {"INCOME": [], "EXPENSE": []}
        for prev in prevs:
            # the same number of days into that year (clamped to its last day)
            cutoff = min(prev.start_date + (as_of - fy.start_date), prev.end_date)
            full, at = actuals(db, prev), actuals(db, prev, cutoff)
            for k in rest:
                rest[k].append(full[k] - at[k])
        p_inc, p_exp = inc + median(rest["INCOME"]), exp + median(rest["EXPENSE"])
        basis = {"kind": "PREVIOUS_YEARS", "fiscal_years": [p.display_name for p in prevs]}
    else:
        months = months_between(fy.start_date, fy.end_date + dt.timedelta(days=1))
        p_inc, p_exp = (_round(Fraction(x) * months / elapsed) for x in (inc, exp))
        basis = {"kind": "THIS_YEAR_PACE", "fiscal_years": []}
    p = p_inc - p_exp
    out["projection"] = {"state": "PROJECTED", "result": fmt(p), "result_word": _word(p), "income": fmt(p_inc),
                         "expense": fmt(p_exp), "basis": basis}
    return out
