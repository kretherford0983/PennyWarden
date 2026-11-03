"""v1.4.1 CR-020: dashboard chart data.

All charts cover one Fiscal Year and use ACTIVE transactions only (VOID excluded). Transfers are excluded: they are
allocated to the protected Budget 0, which is left out of every chart. Budget actuals follow the Budgets page
(the sum of live allocations per budget, children rolled up into their parent budget). Monthly charts bucket by
transaction date within the Fiscal Year's own dates; allocations to this year's budgets dated outside the year are
counted in the pies and budget-vs-actual (as on the Budgets page) but not in the monthly series. Months that have
not started yet (and have no activity) have no value, so lines end at the current month.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import BankAccount, Budget, FiscalYear, RegisterTransaction, TransactionAllocation
from ..money import fmt
from . import bank_accounts as bank
from . import budgets as bsvc
from .common import budget_label, fy_brief, signed_amount

CHART_KEYS = ["income_pie", "monthly", "expense_vs_budget", "balances", "expense_pie", "cumulative_net"]
DEFAULT_CHARTS = ["income_pie", "monthly", "expense_vs_budget"]
PIE_MAX_SLICES = 7  # + "Other" = 8 categorical slots at most
PIE_MIN_SHARE = 0.03  # slices under 3 % are grouped into "Other"


def charts_for(user) -> list[str]:
    raw = getattr(user, "dashboard_charts", None)
    if raw is None:
        return list(DEFAULT_CHARTS)
    return [k for k in raw.split(",") if k in CHART_KEYS]


def _months(fy: FiscalYear) -> list[tuple[dt.date, dt.date]]:
    out = []
    d = fy.start_date.replace(day=1)
    while d <= fy.end_date:
        nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        out.append((max(d, fy.start_date), min(nxt - dt.timedelta(days=1), fy.end_date)))
        d = nxt
    return out


def _pie(rows: list[tuple[str, int]]) -> dict:
    rows = sorted([r for r in rows if r[1] > 0], key=lambda r: (-r[1], r[0]))
    total = sum(v for _l, v in rows)
    keep, other = [], 0
    for label, v in rows:
        if len(keep) < PIE_MAX_SLICES and total and v / total >= PIE_MIN_SHARE:
            keep.append((label, v))
        else:
            other += v
    slices = [{"label": label, "amount": fmt(v), "share": round(v / total, 4)} for label, v in keep]
    if other:
        slices.append({"label": "Other", "amount": fmt(other), "share": round(other / total, 4), "other": True})
    return {"total": fmt(total), "slices": slices}


def data(db: Session, ctx, fy: FiscalYear) -> dict:
    budgets = list(db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id, Budget.status != "DELETED")))
    by_id = {b.id: b for b in budgets}
    parent_of = {b.id: (by_id.get(b.parent_budget_id) or b) for b in budgets}
    zero = {b.id for b in budgets if b.is_budget_zero}

    # per allocation: parent budget, type, date, amount (ACTIVE, live, this FY's budgets, not Budget 0)
    q = (select(TransactionAllocation.budget_id, RegisterTransaction.transaction_date,
                func.sum(signed_amount()))
         .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
         .join(Budget, Budget.id == TransactionAllocation.budget_id)
         .where(Budget.fiscal_year_id == fy.id, RegisterTransaction.status == "ACTIVE",
                TransactionAllocation.removed_at.is_(None))
         .group_by(TransactionAllocation.budget_id, RegisterTransaction.transaction_date))
    per_parent: dict[int, int] = {}
    months = _months(fy)
    monthly = [{"income": 0, "expense": 0} for _ in months]
    for bid, day, cents in db.execute(q):
        if bid in zero or bid not in by_id:
            continue
        p = parent_of[bid]
        cents = int(cents or 0)
        per_parent[p.id] = per_parent.get(p.id, 0) + cents
        kind = "income" if p.budget_type == "INCOME" else "expense"
        for i, (s, e) in enumerate(months):
            if s <= day <= e:
                monthly[i][kind] += cents
                break

    def pie(btype: str) -> dict:
        return _pie([(budget_label(p, None), per_parent.get(p.id, 0)) for p in budgets
                     if p.parent_budget_id is None and not p.is_budget_zero and p.budget_type == btype])

    tree = bsvc.tree(db, fy)
    vs = [{"label": r["label"], "budgeted": r["amount"], "actual": r["actual"], "over_budget": r["over_budget"]}
          for r in tree["expense"] if r["status"] not in ("REJECTED", "INACTIVE")]

    labels = [f"{s:%b %Y}" for s, _e in months]
    today = dt.date.today()
    future = [s > today for s, _e in months]  # months that have not started: no value (the line stops)
    running, cum = 0, []
    for i, m in enumerate(monthly):
        running += m["income"] - m["expense"]
        cum.append(None if future[i] and not (m["income"] or m["expense"]) else fmt(running))

    # 1.7.3 (#88): non-register accounts too, from their balance history (no value before their first entry)
    accounts = list(db.scalars(select(BankAccount).where(BankAccount.workspace_id == ctx.workspace_id,
                                                         BankAccount.status == "ACTIVE")
                               .order_by(*bank.listing_order())))
    series, cents_by_acct = [], []
    for a in accounts:
        opened = a.account_opened_date        # 2.2.0 (#348): no value for months before the account was opened
        if a.register_enabled:
            vals = [bank.current_cents(db, a, as_of=e) if s <= today and (opened is None or e >= opened) else None
                    for s, e in months]
        else:
            vals = [bank.manual_as_of(db, a, min(e, today)) if s <= today and (opened is None or e >= opened) else None
                    for s, e in months]
        cents_by_acct.append(vals)
        series.append({"id": a.id, "label": f"{a.account_name} - {bank.masked(a)}",
                       "values": [None if v is None else fmt(v) for v in vals]})
    totals = []
    for i in range(len(months)):
        col = [v[i] for v in cents_by_acct if v[i] is not None]
        totals.append(fmt(sum(col)) if col else None)

    return {
        "fiscal_year": fy_brief(fy),
        "months": labels,
        "income_by_budget": pie("INCOME"),
        "expense_by_budget": pie("EXPENSE"),
        "monthly": [{"month": labels[i],
                     "income": None if future[i] and not (m["income"] or m["expense"]) else fmt(m["income"]),
                     "expense": None if future[i] and not (m["income"] or m["expense"]) else fmt(m["expense"])}
                    for i, m in enumerate(monthly)],
        "cumulative_net": [{"month": labels[i], "net": cum[i]} for i in range(len(months))],
        "expense_vs_budget": vs,
        "balances": {"accounts": series, "total": totals},
    }
