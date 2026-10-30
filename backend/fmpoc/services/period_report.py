"""2.3.0 (#373): the Quarterly and Annual Fiscal Year financial report (PDF) and presentation (.pptx).

One selection (Fiscal Year + period Q1-Q4 or Annual + optional commentary), two outputs drawn from `build()`.
The rules (recorded in docs/implementation-notes.md as BR-110 to BR-112 of the issue):

- Cutoff (BR-110): everything is as of the end of the period; later-dated transactions are left out. A period still
  in progress is allowed: the cutoff is the run date and the report is *Preliminary - as of <date>*; an Annual
  report for a Fiscal Year that isn't closed is Preliminary too. A period that hasn't started can't be chosen.
- Quarterly isolation (BR-111): other quarters never appear on their own; earlier quarters count only through YTD
  figures. The one exception is a fundraiser's *Revised* row. The Annual report shows Q1-Q4 and the total.
- Fundraiser attribution (BR-112): a fundraiser belongs to the quarter its event ends in (once); only its
  transactions dated on or before the cutoff count ("activity after <date> not included"). A fundraiser of an earlier
  quarter of the same year with transactions dated in the selected quarter is listed as *Revised*.

"Today" is passed in by the caller (computed when the request runs, never at import).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..errors import validation
from ..models import BankAccount, Budget, FiscalYear, Fundraiser, RegisterTransaction, TransactionAllocation
from ..money import fmt
from . import bank_accounts as bank
from . import budgets as bsvc
from . import fundraisers as fsvc
from .common import active_allocation_totals, add_months, fy_brief, quarters

PERIODS = ("Q1", "Q2", "Q3", "Q4", "ANNUAL")
MAX_COMMENTARY = 2000


# ------------------------------------------------------------------ periods (BR-110)
def _q(fy: FiscalYear, name: str) -> tuple[dt.date, dt.date]:
    for n, s, e in quarters(fy):
        if n == name:
            return s, e
    raise validation("Choose Q1, Q2, Q3, Q4 or Annual.", "period")


def options(fy: FiscalYear, today: dt.date) -> list[dict]:
    out = []
    for n, s, e in quarters(fy):
        out.append({"id": n, "label": n, "start_date": s.isoformat(), "end_date": e.isoformat(),
                    "selectable": s <= today, "preliminary": today < e})
    out.append({"id": "ANNUAL", "label": "Annual", "start_date": fy.start_date.isoformat(),
                "end_date": fy.end_date.isoformat(), "selectable": fy.start_date <= today,
                "preliminary": today < fy.end_date or fy.status != "CLOSED"})
    return out


def resolve(fy: FiscalYear, period: str, today: dt.date) -> dict:
    if period not in PERIODS:
        raise validation("Choose Q1, Q2, Q3, Q4 or Annual.", "period")
    start, end = (fy.start_date, fy.end_date) if period == "ANNUAL" else _q(fy, period)
    if start > today:
        raise validation(f"{'The Fiscal Year' if period == 'ANNUAL' else period} hasn't started yet; a period that "
                         "hasn't started can't be reported.", "period")
    cutoff = min(end, today)
    prelim = today < end or (period == "ANNUAL" and fy.status != "CLOSED")
    return {"period": period, "annual": period == "ANNUAL", "start": start, "end": end, "cutoff": cutoff,
            "preliminary": prelim}


def previous_fy(db: Session, fy: FiscalYear) -> FiscalYear | None:
    return db.scalar(select(FiscalYear).where(FiscalYear.workspace_id == fy.workspace_id,
                                              FiscalYear.start_date < fy.start_date)
                     .order_by(FiscalYear.start_date.desc()).limit(1))


def _prior_dates(prior: FiscalYear, p: dict) -> dict:
    """The same period of the prior Fiscal Year: the same quarter (and YTD through it), or the whole year."""
    if p["annual"]:
        return {"start": prior.start_date, "end": prior.end_date, "ytd_end": prior.end_date}
    s, e = _q(prior, p["period"])
    return {"start": s, "end": e, "ytd_end": e}


def _months(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    out, s = [], start
    while s <= end:
        nxt = add_months(s.replace(day=1), 1)
        out.append((s, min(nxt - dt.timedelta(days=1), end)))
        s = nxt
    return out


# ------------------------------------------------------------------ accounts
def _balance(db: Session, a: BankAccount, d: dt.date) -> int | None:
    """The balance at the end of a day by Transaction Date (BR-043, parent totals BR-047): register accounts from
    their transactions, other accounts from their balance history. $0 before *Account opened*; None when there is no
    data for that date (a non-register account before its first entry)."""
    if a.account_opened_date is not None and d < a.account_opened_date:
        return 0
    if a.register_enabled:
        start = bank.register_start(a)
        if start is not None and d < start:
            return None
        return bank.available_cents(db, a, d)
    return bank.manual_as_of(db, a, d)


def _accounts(db: Session, ws_id: int, p: dict, prior: dict | None, fy: FiscalYear) -> list[dict]:
    rows = []
    q_ends = [min(e, p["cutoff"]) for _n, s, e in quarters(fy) if s <= p["cutoff"]]
    for a in db.scalars(select(BankAccount).where(BankAccount.workspace_id == ws_id).order_by(*bank.listing_order())):
        if a.closed_date is not None and a.closed_date < p["start"]:
            continue
        if a.account_opened_date is not None and a.account_opened_date > p["cutoff"]:
            continue
        start = _balance(db, a, p["start"] - dt.timedelta(days=1))
        end = _balance(db, a, p["cutoff"])
        if start is None and end is None:
            continue
        rows.append({"id": a.id, "name": a.account_name, "number": bank.masked(a), "type": a.account_type,
                     "register": a.register_enabled, "closed": a.status == "CLOSED",
                     "start": start, "end": end,
                     "change": None if start is None or end is None else end - start,
                     "quarter_ends": [_balance(db, a, d) for d in q_ends] if p["annual"] else [],
                     "prior_end": _balance(db, a, prior["end"]) if prior else None})
    return rows


# ------------------------------------------------------------------ cash flow (money in / money out, Budget 0 left out)
def _flow(db: Session, ws_id: int, start: dt.date, end: dt.date) -> tuple[int, int]:
    if end < start:
        return 0, 0
    inflow = case((RegisterTransaction.transaction_type == "DEPOSIT", TransactionAllocation.amount_cents), else_=0)
    outflow = case((RegisterTransaction.transaction_type == "WITHDRAWAL", TransactionAllocation.amount_cents), else_=0)
    r = db.execute(select(func.coalesce(func.sum(inflow), 0), func.coalesce(func.sum(outflow), 0))
                   .select_from(TransactionAllocation)
                   .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
                   .join(BankAccount, BankAccount.id == RegisterTransaction.bank_account_id)
                   .join(Budget, Budget.id == TransactionAllocation.budget_id)
                   .where(BankAccount.workspace_id == ws_id, RegisterTransaction.status == "ACTIVE",
                          TransactionAllocation.removed_at.is_(None), Budget.is_budget_zero.is_(False),
                          RegisterTransaction.transaction_date >= start,
                          RegisterTransaction.transaction_date <= end)).one()
    return int(r[0]), int(r[1])


def _flow_row(label: str, io_: tuple[int, int]) -> dict:
    return {"label": label, "in": io_[0], "out": io_[1], "net": io_[0] - io_[1]}


def _cash_flow(db: Session, ws_id: int, fy: FiscalYear, p: dict, prior_fy: FiscalYear | None, prior: dict | None) -> dict:
    months = [_flow_row(s.strftime("%b %Y"), _flow(db, ws_id, s, e)) for s, e in _months(p["start"], p["cutoff"])]
    ytd = _flow_row("Year to date", _flow(db, ws_id, fy.start_date, p["cutoff"]))
    period = _flow_row("Annual" if p["annual"] else p["period"], _flow(db, ws_id, p["start"], p["cutoff"]))
    out = {"months": months, "period": period, "ytd": ytd, "quarters": []}
    if p["annual"]:
        out["quarters"] = [_flow_row(n, _flow(db, ws_id, s, min(e, p["cutoff"]))) for n, s, e in quarters(fy)
                           if s <= p["cutoff"]]
    if prior:
        out["prior_period"] = _flow_row(f"{prior_fy.display_name} {'' if p['annual'] else p['period']}".strip(),
                                        _flow(db, ws_id, prior["start"], prior["end"]))
        out["prior_ytd"] = _flow_row("Prior year to date", _flow(db, ws_id, prior_fy.start_date, prior["ytd_end"]))
    return out


# ------------------------------------------------------------------ budgets
def _shown(x: dict, activity: int) -> bool:
    """Approved budgets; Draft ones while the year isn't approved yet; Rejected / Inactive only with activity."""
    if x.get("is_budget_zero") or x["status"] == "DELETED":
        return False
    if x["status"] in ("REJECTED", "INACTIVE"):
        return activity != 0
    return True


def _members(db: Session, fy: FiscalYear) -> dict[int, list[int]]:
    """Each budget's own id plus, for a parent, every sub-budget's (including a hidden Other: AC-REG-011 roll-up)."""
    out: dict[int, list[int]] = {}
    for b in db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id, Budget.status != "DELETED")):
        out.setdefault(b.id, []).insert(0, b.id)
        if b.parent_budget_id:
            out.setdefault(b.parent_budget_id, []).append(b.id)
    return out


def _budgets(db: Session, fy: FiscalYear, p: dict, prior_fy: FiscalYear | None, prior: dict | None) -> dict:
    tree = bsvc.tree(db, fy)
    mem = _members(db, fy)
    ids = sorted({i for v in mem.values() for i in v})
    ytd = active_allocation_totals(db, ids, None, p["cutoff"])
    if p["annual"]:
        cols = [(n, active_allocation_totals(db, ids, s, min(e, p["cutoff"])) if s <= p["cutoff"] else {})
                for n, s, e in quarters(fy)]
    else:
        cols = [("Quarter", active_allocation_totals(db, ids, p["start"], p["cutoff"]))]
    prior_tot: dict[str, dict] = {}
    if prior_fy is not None and prior is not None:
        pt = bsvc.tree(db, prior_fy)
        pmem = _members(db, prior_fy)
        pids = sorted({i for v in pmem.values() for i in v})
        p_q = active_allocation_totals(db, pids, prior["start"], prior["end"])
        p_ytd = active_allocation_totals(db, pids, None, prior["ytd_end"])
        for r in pt["income"] + pt["expense"]:
            for x in [r, *r["children"]]:
                own = pmem.get(x["id"], [x["id"]])
                prior_tot[f"{x['budget_type']}:{x['display_code']}"] = {
                    "period": sum(p_q.get(i, 0) for i in own), "ytd": sum(p_ytd.get(i, 0) for i in own)}

    def amounts(x: dict) -> dict:
        from ..money import parse_amount
        own = mem.get(x["id"], [x["id"]])
        act = sum(ytd.get(i, 0) for i in own)
        budgeted = parse_amount(x["amount"])
        pr = prior_tot.get(f"{x['budget_type']}:{x['display_code']}")
        return {"id": x["id"], "code": x["display_code"], "label": x["label"], "status": x["state"]["label"],
                "raw_status": x["status"], "budgeted": budgeted,
                "columns": [sum(c.get(i, 0) for i in own) for _n, c in cols],
                "ytd": act, "remaining": budgeted - act,
                "over": act > budgeted and x["budget_type"] == "EXPENSE",
                "above": act > budgeted and x["budget_type"] == "INCOME",
                "prior_period": pr["period"] if pr else None, "prior_ytd": pr["ytd"] if pr else None}

    sections = {}
    for key in ("income", "expense"):
        rows = []
        for r in tree[key]:
            parent = amounts(r)
            if not _shown(r, parent["ytd"]):
                continue
            parent["children"] = [c for c in (amounts(k) for k in r["children"]) if _shown(
                next(k for k in r["children"] if k["id"] == c["id"]), c["ytd"])]
            rows.append(parent)
        counted = [x for x in rows if x["raw_status"] not in ("REJECTED", "INACTIVE")]
        sections[key] = {"rows": rows, "total": {
            "budgeted": sum(x["budgeted"] for x in counted),
            "columns": [sum(x["columns"][i] for x in rows) for i in range(len(cols))],
            "ytd": sum(x["ytd"] for x in rows), "remaining": sum(x["budgeted"] for x in counted) - sum(x["ytd"] for x in rows),
            "prior_period": sum(x["prior_period"] or 0 for x in rows) if prior_tot else None,
            "prior_ytd": sum(x["prior_ytd"] or 0 for x in rows) if prior_tot else None}}
    b0 = None
    if tree["budget_zero"]:
        z = tree["budget_zero"]["id"]
        if ytd.get(z, 0):
            b0 = {"ytd": ytd[z]}
    return {"columns": [n for n, _c in cols], **sections, "budget_zero": b0, "has_prior": bool(prior_tot)}


# ------------------------------------------------------------------ fundraisers (BR-112)
def _fr_totals(rows: list[dict]) -> dict:
    t = fsvc._money_totals(rows)
    return {"gross": t["income"], "expense": t["expense"], "net": t["net"]}


def _fundraisers(db: Session, ctx, fy: FiscalYear, p: dict, fy_income: int) -> dict:
    if not fsvc.module_enabled(db, fy.workspace_id):
        return {"enabled": False, "rows": [], "details": [], "total_gross": 0, "total_net": 0, "period_net": 0}
    from .fundraiser_series import series_history
    frs = [f for f in db.scalars(select(Fundraiser).where(Fundraiser.workspace_id == fy.workspace_id,
                                                         Fundraiser.archived_at.is_(None),
                                                         Fundraiser.cancelled_at.is_(None),
                                                         Fundraiser.end_date >= fy.start_date,
                                                         Fundraiser.end_date <= p["cutoff"])
                                  .order_by(Fundraiser.end_date, Fundraiser.name, Fundraiser.id))]
    qn = {n: (s, e) for n, s, e in quarters(fy)}
    rows, details = [], []
    for f in frs:
        all_rows, _skipped = fsvc._lines(db, f)
        counted = [r for r in all_rows if r["t"].transaction_date <= p["cutoff"]]
        later = any(r["t"].transaction_date > p["cutoff"] and not r["excluded"] for r in all_rows)
        t = _fr_totals(counted)
        quarter = next((n for n, (s, e) in qn.items() if s <= f.end_date <= e), None)
        in_period = p["start"] <= f.end_date <= p["cutoff"]
        row = {"id": f.id, "name": f.name, "start_date": f.start_date.isoformat(), "end_date": f.end_date.isoformat(),
               "quarter": quarter, **t, "after_cutoff": later, "in_period": in_period, "revised": False, "change": None}
        if not p["annual"] and not in_period:
            moved = [r for r in counted if r["t"].transaction_date >= p["start"]]
            if any(not r["excluded"] for r in moved):
                row["revised"] = True
                row["change"] = _fr_totals(moved)["net"]
        rows.append(row)
        if p["annual"] or not in_period:
            continue
        # specifics for a fundraiser that ended in the selected quarter
        lines: dict[tuple[str, str], int] = defaultdict(int)
        labels: dict[int, str] = {}
        for r in counted:
            if r["excluded"] or not r["eff"]:
                continue
            bid = r["a"].budget_id
            if bid not in labels:
                labels[bid] = fsvc.budget_brief(db, db.get(Budget, bid))["label"]
            lines[(r["kind"], labels[bid])] += r["eff"]
        float_out = sum(r["classified"] for r in counted if r["kind"] == "EXPENSE")
        float_back = sum(r["classified"] for r in counted if r["kind"] == "INCOME")
        prev = None
        try:
            hist = series_history(db, ctx, f, {"net_revenue": fmt(t["gross"]), "expenses": fmt(t["expense"]),
                                               "net_proceeds": fmt(t["net"])})
            earlier = [h for h in hist if h["label"] and f.name not in h["label"].split(", ")]
            if earlier:
                h = earlier[-1]
                pn = int(round(float(h["net_proceeds"]) * 100))
                pg = None if h["net_revenue"] is None else int(round(float(h["net_revenue"]) * 100))
                prev = {"year": h["year"], "label": h["label"], "gross": pg, "net": pn, "estimated": h.get("estimated"),
                        "net_change_pct": None if not pn else round((t["net"] - pn) * 100 / abs(pn), 1),
                        "gross_change_pct": None if not pg else round((t["gross"] - pg) * 100 / abs(pg), 1)}
        except Exception:      # noqa: BLE001 - the comparison is optional; never fail the report over it
            prev = None
        details.append({**row, "income_lines": sorted([(k[1], v) for k, v in lines.items() if k[0] == "INCOME"]),
                        "expense_lines": sorted([(k[1], v) for k, v in lines.items() if k[0] == "EXPENSE"]),
                        "seed_out": float_out, "seed_back": float_back, "seed_net": float_back - float_out,
                        "prior_year": prev, "goal": fsvc.goal_vs_actual(f.goal_amount_cents, t["net"])})
    listed = rows if p["annual"] else [r for r in rows if r["in_period"] or r["revised"]]
    total_gross = sum(r["gross"] for r in rows)
    total_net = sum(r["net"] for r in rows)
    return {"enabled": True, "rows": rows, "listed": listed, "details": details,
            "total_gross": total_gross, "total_net": total_net,
            "period_net": sum(r["net"] for r in rows if r["in_period"]),
            "share_of_income": None if not fy_income else round(total_gross * 100 / fy_income, 1)}


# ------------------------------------------------------------------ the whole report
def build(db: Session, ctx, fy: FiscalYear, period: str, today: dt.date, commentary: str | None = None) -> dict:
    p = resolve(fy, period, today)
    prior_fy = previous_fy(db, fy)
    prior = _prior_dates(prior_fy, p) if prior_fy is not None else None
    if commentary is not None:
        commentary = commentary.strip() or None
        if commentary and len(commentary) > MAX_COMMENTARY:
            raise validation(f"The commentary can be at most {MAX_COMMENTARY} characters.", "commentary")
    accounts = _accounts(db, ctx.workspace_id, p, prior, fy)
    flow = _cash_flow(db, ctx.workspace_id, fy, p, prior_fy, prior)
    budgets = _budgets(db, fy, p, prior_fy, prior)
    fr = _fundraisers(db, ctx, fy, p, budgets["income"]["total"]["ytd"])
    shown = budgets["income"]["rows"] + budgets["expense"]["rows"]
    total_end = sum(a["end"] or 0 for a in accounts)
    total_start = sum(a["start"] or 0 for a in accounts)
    label = "Annual" if p["annual"] else p["period"]
    return {
        "fiscal_year": fy_brief(fy), "period": p["period"], "period_label": label, "annual": p["annual"],
        "start_date": p["start"].isoformat(), "end_date": p["end"].isoformat(), "cutoff": p["cutoff"].isoformat(),
        "preliminary": p["preliminary"], "generated_on": today.isoformat(),
        "prior_fiscal_year": fy_brief(prior_fy) if prior_fy else None,
        "prior_start": prior["start"].isoformat() if prior else None,
        "prior_end": prior["end"].isoformat() if prior else None,
        "commentary": commentary,
        "highlights": {"total_cash": total_end, "net_cash_change": total_end - total_start,
                       "budgets_over": sum(1 for x in shown if x["remaining"] < 0),
                       "budgets_within": sum(1 for x in shown if x["remaining"] >= 0),
                       "fundraiser_net": fr["total_net"] if p["annual"] else fr["period_net"],
                       "fundraisers_on": fr["enabled"]},
        "accounts": accounts, "quarter_names": [n for n, s, _e in quarters(fy) if s <= p["cutoff"]],
        "cash_flow": flow, "budgets": budgets, "fundraisers": fr,
    }
