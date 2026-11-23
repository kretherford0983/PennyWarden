"""2.5.0 (#590): the Budget proposal - a Fiscal Year's budgets presented for approval, beside the previous year.

Decided with Kyle (2026-11-23):

* Budget Managers only (budget.manage). The year may be Draft (titled *Proposed*) or Approved (*Approved*); a Closed
  year is history, not a proposal. Rejected budgets are left out.
* Columns per line: the previous year's budget, the previous year's actual - *projected* to the year end while that
  year is still running (the Budget Review projection, honouring the user's Budget Review projection choices) - the
  proposed amount and the change from the previous year's budget.
* Lines match through the #89 continuation links, else the same code (the Budget Review's `_successor`), so a renamed
  or renumbered budget is one line. A new budget shows "-" for the previous year. A previous-year budget with no
  successor is listed under *Not in <year>* with "-" proposed, so approvers see what was dropped.
* Totals: proposed = the year's parents (not rejected); previous budget / actual = all of the previous year's
  parents, so the totals equal the previous year's own totals.

Also appended to the Annual report (period_report) when a Budget Manager asks for it.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import validation
from ..models import Budget, FiscalYear, utcnow
from ..money import fmt
from .budget_planning import (_actual_all, _code, _kids, _successor, basis, choices, choosable_ids, pct, project,
                              structure)
from .common import active_allocation_totals, fy_brief

MAX_COMMENTARY = 2000
DROPPED = ("REJECTED", "DELETED")


def previous_fy(db: Session, fy: FiscalYear) -> FiscalYear | None:
    return db.scalar(select(FiscalYear).where(FiscalYear.workspace_id == fy.workspace_id,
                                              FiscalYear.start_date < fy.start_date)
                     .order_by(FiscalYear.start_date.desc()).limit(1))


def next_fy(db: Session, fy: FiscalYear) -> FiscalYear | None:
    return db.scalar(select(FiscalYear).where(FiscalYear.workspace_id == fy.workspace_id,
                                              FiscalYear.start_date > fy.start_date)
                     .order_by(FiscalYear.start_date).limit(1))


def check_year(fy: FiscalYear) -> None:
    if fy.status == "CLOSED":
        raise validation(f"{fy.display_name} is closed. A budget proposal is for a Draft or Approved Fiscal Year.",
                         "fiscal_year_id")


def state_word(fy: FiscalYear) -> str:
    return "Proposed" if fy.status == "DRAFT" else "Approved"


def build(db: Session, ctx, fy: FiscalYear, today: dt.date, commentary: str | None = None) -> dict:
    check_year(fy)
    commentary = (commentary or "").strip() or None
    if commentary and len(commentary) > MAX_COMMENTARY:
        raise validation(f"The commentary can be at most {MAX_COMMENTARY} characters.", "commentary")
    prev = previous_fy(db, fy)
    word = state_word(fy)

    # ---- the previous year: budgets, actual (whole year, or projected while the year runs)
    prev_struct = structure(db, prev) if prev else {"INCOME": [], "EXPENSE": []}
    ended = prev is not None and today > prev.end_date
    bas = basis(prev, today) if prev and not ended else None
    ch = choices(db, ctx, prev, prev_struct) if prev and not ended else {}
    all_prev = list(db.scalars(select(Budget.id).where(Budget.fiscal_year_id == prev.id))) if prev else []
    ytd = active_allocation_totals(db, all_prev, None, today) if bas else {}
    cache: dict[int, int] = {}
    too_early = bas is not None and bas["state"] == "TOO_EARLY"

    def proj(bid: int, y: int) -> int:
        """The Budget Review projection of one choosable row (its own projection choice)."""
        if too_early or not ch.get(bid, {}).get("project", True):
            return y
        v = project(y, bas)
        return y if v is None else v

    def prev_actual(b: Budget, shown_kids: list[Budget]) -> int:
        if ended:
            return _actual_all(db, b, cache)            # whole year; a parent includes its sub-budgets
        if b.parent_budget_id is not None:
            return proj(b.id, ytd.get(b.id, 0))
        fam = [b.id] + [k.id for k in _kids(db, b.id)]
        total = sum(ytd.get(i, 0) for i in fam)
        if not shown_kids:                              # a simple budget: projected as one row
            return proj(b.id, total)
        rest = total - sum(ytd.get(k.id, 0) for k in shown_kids)   # sub-budgets not listed: year to date
        return rest + sum(proj(k.id, ytd.get(k.id, 0)) for k in shown_kids)

    # previous-year budget -> its successor in this year (links, else same code)
    succ: dict[int, int] = {}
    prev_rows: list[tuple[str, Budget, Budget | None, list[Budget]]] = []
    for key, rows in prev_struct.items():
        for r in rows:
            p = r["budget"]
            if p.status in DROPPED:
                continue
            prev_rows.append((key, p, None, r["children"]))
            s = _successor(db, p, fy)
            if s is not None:
                succ[s.id] = p.id
            for k in r["children"]:
                if k.status in DROPPED:
                    continue
                prev_rows.append((key, k, p, []))
                sk = _successor(db, k, fy)
                if sk is not None:
                    succ[sk.id] = k.id
    prev_vals: dict[int, tuple[int, int]] = {}
    for _k, b, parent, kids in prev_rows:
        prev_vals[b.id] = (b.amount_cents, prev_actual(b, kids if parent is None else []))

    def line(b: Budget, label: str, level: str) -> dict:
        pid = succ.get(b.id)
        pb, pa = prev_vals.get(pid, (None, None)) if pid else (None, None)
        change = b.amount_cents - pb if pb is not None else None
        return {"id": b.id, "level": level, "code": _code(db, b), "name": b.name, "label": label,
                "status": b.status, "previous_id": pid,
                "previous_budget": pb, "previous_actual": pa, "proposed": b.amount_cents,
                "change": change, "change_pct": pct(change, pb) if pb else None}

    struct = structure(db, fy)
    sections: dict[str, dict] = {}
    for key, rows in struct.items():
        out = []
        for r in rows:
            p = r["budget"]
            if p.status in DROPPED:
                continue
            label = _code(db, p) + " " + p.name
            row = line(p, label, "parent")
            row["children"] = [line(k, _code(db, k) + " " + k.name, "sub") for k in r["children"]
                               if k.status not in DROPPED]
            out.append(row)
        matched = set(succ.values())
        dropped = []
        for k2, b, parent, _kids2 in prev_rows:
            if k2 != key or b.id in matched:
                continue
            if parent is not None and parent.id not in matched:
                continue        # the whole parent is listed as dropped; its sub-budgets go with it
            if b.is_other and not b.amount_cents:
                continue
            pb, pa = prev_vals[b.id]
            dropped.append({"id": b.id, "level": "parent" if parent is None else "sub", "code": _code(db, b),
                            "name": b.name, "label": _code(db, b) + " " + b.name, "previous_budget": pb,
                            "previous_actual": pa, "proposed": None, "change": -pb if pb else None,
                            "change_pct": pct(-pb, pb) if pb else None})
        prev_parents = [b for k2, b, parent, _x in prev_rows if k2 == key and parent is None]
        total_prev = sum(b.amount_cents for b in prev_parents) if prev else None
        total_prev_actual = sum(prev_vals[b.id][1] for b in prev_parents) if prev else None
        total = sum(r["proposed"] for r in out)
        sections[key.lower()] = {
            "rows": out, "not_in_year": dropped,
            "total": {"previous_budget": total_prev, "previous_actual": total_prev_actual, "proposed": total,
                      "change": total - total_prev if prev else None,
                      "change_pct": pct(total - total_prev, total_prev) if prev and total_prev else None}}
    inc, exp = sections["income"]["total"], sections["expense"]["total"]
    net = {"proposed": inc["proposed"] - exp["proposed"],
           "previous_budget": inc["previous_budget"] - exp["previous_budget"] if prev else None,
           "previous_actual": inc["previous_actual"] - exp["previous_actual"] if prev else None}
    actual_word = None
    if prev:
        actual_word = "actual" if ended else ("YTD actual" if too_early else "projected")
    return {
        "fiscal_year": fy_brief(fy), "state": word, "previous_fiscal_year": fy_brief(prev) if prev else None,
        "previous_ended": ended, "actual_word": actual_word,
        "projection_basis": ({"state": bas["state"], "elapsed_months": f"{float(bas['elapsed']):.2f}",
                              "months": f"{float(bas['months']):.2f}"} if bas else None),
        "income": sections["income"], "expense": sections["expense"], "net": net,
        "commentary": commentary, "as_of": today.isoformat(), "generated_at": utcnow().isoformat(timespec="seconds"),
    }


def title(rep: dict) -> str:
    return f"{rep['fiscal_year']['display_name']} Budget — {rep['state']}"


def column_heads(rep: dict) -> list[str]:
    py = rep["previous_fiscal_year"]
    fy = rep["fiscal_year"]["display_name"]
    if not py:
        return ["Budget", f"{fy} {rep['state'].lower()}"]
    return ["Budget", f"{py['display_name']} budget", f"{py['display_name']} {rep['actual_word']}",
            f"{fy} {rep['state'].lower()}", "Change"]


def notes_lines(rep: dict) -> list[str]:
    out = []
    py = rep["previous_fiscal_year"]
    if not py:
        out.append("There is no earlier Fiscal Year, so only the proposed amounts are shown.")
    else:
        if rep["actual_word"] == "projected":
            b = rep["projection_basis"]
            out.append(f"{py['display_name']} is still running: its actual is projected to the year end from the "
                       f"average monthly activity so far ({b['elapsed_months']} of {b['months']} months), as in the "
                       "Budget Review.")
        elif rep["actual_word"] == "YTD actual":
            out.append(f"{py['display_name']} has run less than a month: its actual is the year to date, not a projection.")
        out.append("Change = the proposed amount minus last year's budget. Lines are matched through their "
                   "\"continues from\" link, else by code.")
    if rep["state"] == "Proposed":
        out.append("Proposed: the Fiscal Year is a Draft; the amounts may still change before it is approved.")
    out.append("Gross amounts: an income budget counts the money received, an expense budget the money spent.")
    return out


def money_or_dash(c: int | None) -> str:
    return "—" if c is None else fmt(c)


def json_out(rep: dict) -> dict:
    """The JSON shape returned to the screen: amounts as strings."""
    def conv(x):
        if isinstance(x, dict):
            return {k: (money_or_dash(v) if k in ("previous_budget", "previous_actual", "proposed", "change") else conv(v))
                    for k, v in x.items()}
        if isinstance(x, list):
            return [conv(v) for v in x]
        return x
    return conv(rep)
