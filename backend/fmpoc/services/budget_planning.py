"""2.1.0 budget planning: the Budget Prep report (#257) and the Fiscal Year Planning Sheet (#261).

Both are for Budget Managers only (budget.manage) and share:

* **History** - the #89 continuation links (`Budget.continues_budget_id`), so a renumbered budget or one missing for a
  year is still one line. A sub-budget follows its own link; without one its history is on the parent's row. *Other*
  has no link of its own (BR-017): it follows its parent's line (the Other of each earlier parent).
* **Actuals** - ACTIVE allocations only (BR-048), the same sums as the Budgets page; a parent's actual is its own plus
  its sub-budgets'. The current year's actual is year-to-date: allocations dated on or before the report date.
* **Projection** - average monthly activity so far in the Fiscal Year, carried to the Fiscal Year end:
  YTD / elapsed months x months in the year, counting whole and partial months (a month is the span from the
  Fiscal Year's start day to the same day of the next month). Less than one month elapsed: *too early to project*.
  On or after the last day of the year the actual is final. Parent rows with sub-budgets project as the sum of their
  sub-budgets (projected or YTD).
* **Projection choices** - per user and per budget (so per Fiscal Year), remembered in budget_projection_choice.
  Every budget is projected by default except one linked to fundraisers that have all ended, been cancelled or been
  archived (a finished fundraiser receives nothing more). The choice is made on the rows that carry activity: a
  parent without sub-budgets, or each sub-budget (Other included).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import tempfile
from fractions import Fraction
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import CondPageBreak, KeepTogether, PageBreak, Paragraph, Spacer, Table, TableStyle
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..errors import validation
from ..models import Budget, BudgetProjectionChoice, FiscalYear, Fundraiser, FundraiserBudget, Workspace, utcnow
from ..money import fmt
from . import budgets as bsvc
from . import fundraisers as fsvc
from .common import active_allocation_totals, add_months, budget_display_code, fy_brief
from . import branding
from .reports import _FONT, BODY_H, MARGIN, PM, P, S, _AuditDoc, _csv_safe, _Mark, _stamp_and_write, gross_note, money

COMPLETE_FUNDRAISER = {"ENDED", "CANCELLED", "ARCHIVED"}
STATUS_TEXT = {"APPROVED": "Approved", "DRAFT": "Draft", "REJECTED": "Rejected", "INACTIVE": "Inactive",
               "DELETED": "Deleted"}
MAX_YEARS = 50


# ------------------------------------------------------------------ projection
def months_between(start: dt.date, stop: dt.date) -> Fraction:
    """Months from `start` up to (not including) `stop`: whole months, then the partial month as a fraction of its
    length in days."""
    if stop <= start:
        return Fraction(0)
    m = 0
    while add_months(start, m + 1) <= stop:
        m += 1
    a, b = add_months(start, m), add_months(start, m + 1)
    return m + Fraction((stop - a).days, (b - a).days)


def basis(fy: FiscalYear, as_of: dt.date) -> dict:
    months = months_between(fy.start_date, fy.end_date + dt.timedelta(days=1))
    if as_of >= fy.end_date:
        return {"state": "YEAR_ENDED", "elapsed": months, "months": months}
    elapsed = months_between(fy.start_date, as_of + dt.timedelta(days=1))   # the report date counts as elapsed
    return {"state": "TOO_EARLY" if elapsed < 1 else "PROJECT", "elapsed": elapsed, "months": months}


def _round(x: Fraction) -> int:
    """Half away from zero, to the cent."""
    n = int(abs(x) + Fraction(1, 2))
    return n if x >= 0 else -n


def project(ytd: int, b: dict) -> int | None:
    if b["state"] == "TOO_EARLY":
        return None
    if b["state"] == "YEAR_ENDED":
        return ytd
    return _round(Fraction(ytd) * b["months"] / b["elapsed"])


# ------------------------------------------------------------------ figures
def pct(diff: int, base: int) -> str | None:
    """Percent of `base`, one decimal, None when base is 0 (printed n/a)."""
    if base == 0:
        return None
    v = _round(Fraction(diff * 1000, abs(base)))      # tenths of a percent
    sign = "-" if v < 0 else ""
    v = abs(v)
    return f"{sign}{v // 10}.{v % 10}"


def direction(diff: int) -> str:
    return "over" if diff > 0 else "under" if diff < 0 else "on budget"


def compare(budgeted: int, actual: int) -> dict:
    d = actual - budgeted
    return {"budgeted": fmt(budgeted), "actual": fmt(actual), "difference": fmt(d), "difference_pct": pct(d, budgeted),
            "direction": direction(d)}


def diff_text(c: dict, key: str = "difference") -> str:
    d = c[key]
    if d is None:
        return ""
    p = c.get(f"{key}_pct")
    if d in ("0.00", "-0.00"):
        return "on budget"
    word = "over" if not d.startswith("-") else "under"
    return f"{money(d.lstrip('-'))} {word} ({'n/a' if p is None else p.lstrip('-') + '%'})"


# ------------------------------------------------------------------ structure of the current year
def _kids(db: Session, parent_id: int) -> list[Budget]:
    return list(db.scalars(select(Budget).where(Budget.parent_budget_id == parent_id, Budget.status != "DELETED")))


def _other_of(db: Session, parent: Budget | None) -> Budget | None:
    if parent is None:
        return None
    return db.scalar(select(Budget).where(Budget.parent_budget_id == parent.id, Budget.is_other.is_(True),
                                          Budget.status != "DELETED"))


def structure(db: Session, fy: FiscalYear) -> dict[str, list[dict]]:
    """Income and Expense: parents (not Budget 0, not deleted) with the sub-budgets the Budgets page shows (Other
    where it is selectable or carries activity - BR-019)."""
    t = bsvc.tree(db, fy)
    out: dict[str, list[dict]] = {}
    for key, section in (("INCOME", t["income"]), ("EXPENSE", t["expense"])):
        rows = []
        for r in section:
            p = db.get(Budget, r["id"])
            rows.append({"budget": p, "simple": r["simple"],
                         "children": [db.get(Budget, c["id"]) for c in r["children"]]})
        out[key] = rows
    return out


def choosable_ids(struct: dict[str, list[dict]]) -> list[int]:
    ids = []
    for rows in struct.values():
        for r in rows:
            if r["children"]:
                ids += [c.id for c in r["children"]]
            else:
                ids.append(r["budget"].id)
    return ids


def _fundraisers_by_budget(db: Session, ids: list[int]) -> dict[int, list[Fundraiser]]:
    """Fundraisers linked to each budget, directly or through its parent (a parent includes its children)."""
    if not ids:
        return {}
    parents = {b.id: b.parent_budget_id for b in db.scalars(select(Budget).where(Budget.id.in_(ids)))}
    want = set(ids) | {p for p in parents.values() if p}
    links = db.execute(select(FundraiserBudget.budget_id, Fundraiser).join(
        Fundraiser, Fundraiser.id == FundraiserBudget.fundraiser_id).where(FundraiserBudget.budget_id.in_(want))).all()
    by: dict[int, list[Fundraiser]] = {}
    for bid, f in links:
        by.setdefault(bid, []).append(f)
    out = {}
    for i in ids:
        fs = {f.id: f for f in by.get(i, []) + by.get(parents.get(i) or -1, [])}
        out[i] = list(fs.values())
    return out


def choices(db: Session, ctx, fy: FiscalYear, struct: dict | None = None) -> dict[int, dict]:
    struct = struct or structure(db, fy)
    ids = choosable_ids(struct)
    saved = {c.budget_id: c.project for c in db.scalars(select(BudgetProjectionChoice).where(
        BudgetProjectionChoice.user_id == ctx.user.id, BudgetProjectionChoice.budget_id.in_(ids)))} if ids else {}
    frs = _fundraisers_by_budget(db, ids)
    today = dt.date.today()
    out = {}
    for i in ids:
        fl = frs.get(i, [])
        done = [f for f in fl if fsvc.status_of(f, today) in COMPLETE_FUNDRAISER]
        default = not (fl and len(done) == len(fl))
        out[i] = {"budget_id": i, "project": saved.get(i, default), "default": default, "saved": i in saved,
                  "complete_fundraisers": [f.name for f in done] if not default else []}
    return out


def choices_view(db: Session, ctx, fy: FiscalYear) -> dict:
    struct = structure(db, fy)
    ch = choices(db, ctx, fy, struct)
    sections = {}
    for key, rows in struct.items():
        items = []
        for r in rows:
            p = r["budget"]
            items.append({"budget_id": p.id, "code": p.parent_code, "name": p.name, "level": "parent",
                          "choosable": not r["children"], **({k: v for k, v in ch[p.id].items() if k != "budget_id"}
                                                            if not r["children"] else {})})
            for c in r["children"]:
                items.append({"budget_id": c.id, "code": budget_display_code(c, p), "name": c.name, "level": "sub",
                              "choosable": True, **{k: v for k, v in ch[c.id].items() if k != "budget_id"}})
        sections[key.lower()] = items
    return {"fiscal_year": fy_brief(fy), **sections}


def save_choices(db: Session, ctx, fy: FiscalYear, items, reset: bool) -> dict:
    struct = structure(db, fy)
    allowed = set(choosable_ids(struct))
    if reset:
        if allowed:
            db.execute(delete(BudgetProjectionChoice).where(BudgetProjectionChoice.user_id == ctx.user.id,
                                                            BudgetProjectionChoice.budget_id.in_(allowed)))
    seen = set()
    for it in items:
        if it.budget_id not in allowed:
            raise validation("Choose budgets of this Fiscal Year that carry activity (a budget without sub-budgets, "
                             "or a sub-budget).", "choices")
        if it.budget_id in seen:
            raise validation("A budget is listed twice.", "choices")
        seen.add(it.budget_id)
        row = db.scalar(select(BudgetProjectionChoice).where(BudgetProjectionChoice.user_id == ctx.user.id,
                                                             BudgetProjectionChoice.budget_id == it.budget_id))
        if row is None:
            db.add(BudgetProjectionChoice(workspace_id=ctx.workspace_id, user_id=ctx.user.id, budget_id=it.budget_id,
                                          project=it.project))
        else:
            row.project = it.project
    db.flush()
    return choices_view(db, ctx, fy)


# ------------------------------------------------------------------ history
def _predecessors(db: Session, b: Budget) -> dict[int, Budget]:
    """fiscal_year_id -> the earlier budget on this budget's line (the #89 links)."""
    out, seen, cur = {}, {b.id}, b
    while cur.continues_budget_id and cur.continues_budget_id not in seen:
        cur = db.get(Budget, cur.continues_budget_id)
        if cur is None:
            break
        seen.add(cur.id)
        if cur.status != "DELETED":
            out.setdefault(cur.fiscal_year_id, cur)
    return out


def _line(db: Session, b: Budget) -> tuple[dict[int, Budget], str | None]:
    """The earlier budgets of a row, and a note when the row has no line of its own."""
    if b.parent_budget_id is None:
        return _predecessors(db, b), None
    if b.is_other:   # Other follows its parent's line
        parent = db.get(Budget, b.parent_budget_id)
        out = {}
        for fy_id, p in _predecessors(db, parent).items():
            o = _other_of(db, p)
            if o is not None:
                out[fy_id] = o
        return out, None
    if b.continues_budget_id:
        return _predecessors(db, b), None
    return {}, "history on parent"


def _successor(db: Session, b: Budget, next_fy: FiscalYear | None) -> Budget | None:
    """The next year's budget on this budget's line: the #89 continuation link, else (build 3 feedback, 2026-10-20)
    a next-year budget with the same code, type and level that continues nothing - so a draft entered by hand or
    copied without links still lines up with the budget it replaces instead of being listed twice."""
    if next_fy is None:
        return None
    if b.is_other and b.parent_budget_id:
        # Other follows its parent; a next-year parent without sub-budgets has no separate Other line
        p = _successor(db, db.get(Budget, b.parent_budget_id), next_fy)
        if p is None or not bsvc.children_of(db, p)[0]:
            return None
        return _other_of(db, p)
    nxt = bsvc._continued_by(db, b.id)
    if nxt is not None:
        return nxt if nxt.fiscal_year_id == next_fy.id else None
    return _same_code(db, b, next_fy)


def _same_code(db: Session, b: Budget, next_fy: FiscalYear) -> Budget | None:
    q = select(Budget).where(Budget.fiscal_year_id == next_fy.id, Budget.budget_type == b.budget_type,
                             Budget.status != "DELETED", Budget.continues_budget_id.is_(None),
                             Budget.system_managed.is_(False))
    if b.parent_budget_id is None:
        return db.scalar(q.where(Budget.parent_budget_id.is_(None), Budget.parent_code == b.parent_code).limit(1))
    parent = db.get(Budget, b.parent_budget_id)
    np = _successor(db, parent, next_fy)
    if np is None:
        return None
    return db.scalar(q.where(Budget.parent_budget_id == np.id, Budget.child_code == b.child_code).limit(1))


def _actual_all(db: Session, b: Budget, totals_cache: dict[int, int]) -> int:
    """Whole-year actual as on the Budgets page (a parent includes its sub-budgets)."""
    ids = [b.id] + ([k.id for k in db.scalars(select(Budget).where(Budget.parent_budget_id == b.id))]
                    if b.parent_budget_id is None else [])
    missing = [i for i in ids if i not in totals_cache]
    if missing:
        got = active_allocation_totals(db, missing)
        for i in missing:
            totals_cache[i] = got.get(i, 0)
    return sum(totals_cache[i] for i in ids)


def _code(db: Session, b: Budget) -> str:
    return budget_display_code(b, db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None)


def adjacent_years(db: Session, ws_id: int, fy: FiscalYear) -> tuple[list[FiscalYear], FiscalYear | None]:
    prior = list(db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id,
                                                     FiscalYear.start_date < fy.start_date)
                            .order_by(FiscalYear.start_date.desc())))
    nxt = db.scalar(select(FiscalYear).where(FiscalYear.workspace_id == ws_id, FiscalYear.start_date > fy.start_date)
                    .order_by(FiscalYear.start_date).limit(1))
    return prior, nxt


# ------------------------------------------------------------------ Budget Prep report (#257)
def budget_review(db: Session, ctx, fy: FiscalYear, *, years: int = 3, projected: bool = False,
                include_next: bool = False, budget_id: int | None = None, parent_budget_id: int | None = None,
                as_of: dt.date | None = None) -> dict:
    as_of = as_of or dt.date.today()
    if years < 0:
        years = MAX_YEARS
    prior, next_fy = adjacent_years(db, ctx.workspace_id, fy)
    # 2.2.0 (#284): after the Fiscal Years in PennyWarden come the years before it with entered figures (newest first)
    from . import budget_history as hist
    first = hist.first_year(db, ctx.workspace_id)
    entered_labels = hist.year_labels(db, ctx.workspace_id, first)
    columns = [("fy", y) for y in prior] + [("entered", y) for y in sorted(entered_labels, reverse=True)]
    shown = list(reversed(columns[:min(years, MAX_YEARS)]))             # oldest first
    fig_cache: dict[int, dict] = {}

    def entered_of(b: Budget) -> dict:
        if b.id not in fig_cache:
            fig_cache[b.id] = hist.figures(db, b, first)
        return fig_cache[b.id]
    struct = structure(db, fy)
    ch = choices(db, ctx, fy, struct) if projected else {}
    bas = basis(fy, as_of)
    all_ids = [b.id for b in db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id))]
    ytd = active_allocation_totals(db, all_ids, None, as_of)
    cache: dict[int, int] = {}

    def history(b: Budget, code: str) -> tuple[list, str | None]:
        line, note = _line(db, b)
        cells = []
        for kind, y in shown:
            if kind == "entered":
                f = entered_of(b).get(y)
                if f is None:
                    cells.append(None)
                    continue
                note = None      # an entered figure of its own: the row has history even without a link
                # 2.2.0 (#381): what the budget was called that year, when it differs from this row
                as_ = f"{f['code']} {f['name']}" if f.get("code") and (f["code"], f["name"]) != (code, b.name) else None
                cells.append({"source": "ENTERED", "fiscal_year_id": None, "budget_id": None, "code": code,
                              "name": b.name, "status": None, "renumbered": False, "entered_as": as_,
                              "from_sub_budgets": f["source"] == "subs", "mismatch": f["mismatch"],
                              **compare(f["budgeted"], f["actual"])})
                continue
            x = line.get(y.id)
            if x is None:
                cells.append(None)
                continue
            xc = _code(db, x)
            cells.append({"source": "RECORDED", "fiscal_year_id": y.id, "budget_id": x.id, "code": xc, "name": x.name,
                          "status": x.status, "renumbered": xc != code,
                          **compare(x.amount_cents, _actual_all(db, x, cache))})
        if note and any(c is not None for c in cells):
            note = None
        return cells, note

    def nxt(b: Budget) -> dict | None:
        if not include_next:
            return None
        n = _successor(db, b, next_fy)
        if n is None:
            return None
        change = n.amount_cents - b.amount_cents
        return {"budget_id": n.id, "code": _code(db, n), "name": n.name, "status": n.status, "amount": fmt(n.amount_cents),
                "change": fmt(change), "change_pct": pct(change, b.amount_cents), "direction": direction(change)}

    def leaf_projection(b: Budget, y: int) -> tuple[dict, int]:
        choice = ch[b.id]["project"]
        if not choice:
            return {"state": "NOT_PROJECTED", "choice": False, "projected": fmt(y)}, y
        v = project(y, bas)
        if v is None:
            return {"state": "TOO_EARLY", "choice": True, "projected": None}, y
        return {"state": bas["state"] if bas["state"] == "YEAR_ENDED" else "PROJECTED", "choice": True,
                "projected": fmt(v)}, v

    def with_diff(pr: dict, budgeted: int) -> dict:
        if pr.get("projected") is None:
            return {**pr, "difference": None, "difference_pct": None, "direction": None}
        from ..money import parse_amount
        d = parse_amount(pr["projected"], allow_negative=True) - budgeted
        return {**pr, "difference": fmt(d), "difference_pct": pct(d, budgeted), "direction": direction(d)}

    def average(cells: list) -> dict | None:
        """#283: the average budgeted, actual and difference of the prior years shown that the budget existed."""
        got = [c for c in cells if c is not None]
        if not got:
            return None
        from ..money import parse_amount
        b = _round(Fraction(sum(parse_amount(c["budgeted"], allow_negative=True) for c in got), len(got)))
        a = _round(Fraction(sum(parse_amount(c["actual"], allow_negative=True) for c in got), len(got)))
        return {**compare(b, a), "years": len(got)}

    sections: dict[str, list[dict]] = {}
    for key, rows in struct.items():
        out = []
        for r in rows:
            p, kids = r["budget"], r["children"]
            if parent_budget_id is not None and p.id != parent_budget_id:
                continue
            fam = [p.id] + [k.id for k in _kids(db, p.id)]
            p_ytd = sum(ytd.get(i, 0) for i in fam)
            code = p.parent_code
            child_rows, roll, too_early = [], 0, False
            for k in kids:
                kcode = budget_display_code(k, p)
                k_ytd = ytd.get(k.id, 0)
                h, note = history(k, kcode)
                row = {"id": k.id, "level": "sub", "parent_id": p.id, "code": kcode, "name": k.name,
                       "budget_type": k.budget_type, "status": k.status, "state": bsvc.state(k), "is_other": k.is_other,
                       "history": h, "history_note": note, "average": average(h),
                       "current": compare(k.amount_cents, k_ytd),
                       "projection": None, "next": nxt(k), "choosable": True}
                if projected:
                    pr, v = leaf_projection(k, k_ytd)
                    too_early |= pr["state"] == "TOO_EARLY"
                    roll += v
                    row["projection"] = with_diff(pr, k.amount_cents)
                child_rows.append(row)
            h, note = history(p, code)
            prow = {"id": p.id, "level": "parent", "parent_id": None, "code": code, "name": p.name,
                    "budget_type": p.budget_type, "status": p.status, "state": bsvc.state(p), "is_other": False, "history": h,
                    "history_note": note, "average": average(h), "current": compare(p.amount_cents, p_ytd), "projection": None,
                    "next": nxt(p), "choosable": not kids}
            if projected:
                if kids:
                    # sub-budgets not listed (a zero Other without activity) and the parent's own allocations: YTD
                    rest = p_ytd - sum(ytd.get(k.id, 0) for k in kids)
                    pr = ({"state": "TOO_EARLY", "choice": None, "projected": None} if too_early and bas["state"] == "TOO_EARLY"
                          else {"state": "ROLLUP", "choice": None, "projected": fmt(roll + rest)})
                else:
                    pr, _v = leaf_projection(p, p_ytd)
                prow["projection"] = with_diff(pr, p.amount_cents)
            group = [prow, *child_rows]
            if budget_id is not None:
                group = [x for x in group if x["id"] == budget_id]
            out += group
        sections[key.lower()] = out
    if budget_id is not None and not (sections["income"] or sections["expense"]):
        raise validation("Choose a budget of this Fiscal Year (not Budget 0).", "budget_id")
    if parent_budget_id is not None and not (sections["income"] or sections["expense"]):
        raise validation("Choose a parent budget of this Fiscal Year (not Budget 0).", "parent_budget_id")
    return {
        "fiscal_year": fy_brief(fy), "as_of": as_of.isoformat(),
        "years": [{**fy_brief(y), "entered": False} if kind == "fy" else
                  {"id": None, "display_name": entered_labels[y], "label": entered_labels[y], "status": None,
                   "start_date": None, "end_date": None, "entered": True, "year": y} for kind, y in shown],
        "available_years": len(columns), "entered_years": len(entered_labels), "projected": projected, "include_next": include_next,
        "next_fiscal_year": fy_brief(next_fy) if include_next else None,
        "projection_basis": ({"state": bas["state"], "elapsed_months": f"{float(bas['elapsed']):.2f}",
                              "months": f"{float(bas['months']):.2f}"} if projected else None),
        "filter": {"budget_id": budget_id, "parent_budget_id": parent_budget_id},
        "income": sections["income"], "expense": sections["expense"],
        "generated_at": utcnow().isoformat(timespec="seconds"),
    }


def _us(d: str | dt.date) -> str:
    d = dt.date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d.month}/{d.day}/{d.year}"


PROJ_TEXT = {"NOT_PROJECTED": "Complete: no projection", "TOO_EARLY": "too early to project"}


def budget_review_csv(rep: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    head = ["Section", "Level", "Code", "Budget", "Status"]
    for y in rep["years"]:
        n = y["display_name"] + (" (entered)" if y.get("entered") else "")   # 2.2.0 (#284)
        head += [f"{n} code", f"{n} budgeted", f"{n} actual", f"{n} difference", f"{n} difference %", f"{n} status"]
    head += ["Avg budgeted", "Avg actual", "Avg difference", "Avg years"]          # #283
    cur = rep["fiscal_year"]["display_name"]
    head += [f"{cur} budgeted", f"{cur} actual YTD {rep['as_of']}", f"{cur} difference", f"{cur} difference %",
             "History note"]
    if rep["projected"]:
        head += ["Projection", "Projected", "Projected difference", "Projected difference %"]
    if rep["include_next"]:
        nn = rep["next_fiscal_year"]["display_name"] if rep["next_fiscal_year"] else "Next year"
        head += [f"{nn} code", f"{nn} amount", f"{nn} status", "Change", "Change %"]
    w.writerow([_csv_safe(h) for h in head])   # 2.2.0 (#284): entered year labels are typed by users
    for sec in ("income", "expense"):
        for r in rep[sec]:
            line = [sec.title(), "Sub-budget" if r["level"] == "sub" else "Budget", r["code"], r["name"],
                    STATUS_TEXT.get(r["status"], r["status"])]
            for c in r["history"]:
                line += (["", "—", "—", "", "", ""] if c is None else
                         [c["code"], c["budgeted"], c["actual"], c["difference"], c["difference_pct"] or "n/a",
                          _entered_text(c) if c.get("source") == "ENTERED" else STATUS_TEXT.get(c["status"], c["status"])])
            av = r.get("average")
            line += (["", "", "", 0] if av is None else [av["budgeted"], av["actual"], av["difference"], av["years"]])
            cu = r["current"]
            line += [cu["budgeted"], cu["actual"], cu["difference"], cu["difference_pct"] or "n/a", r["history_note"] or ""]
            if rep["projected"]:
                pr = r["projection"] or {}
                state = pr.get("state")
                line += [{"PROJECTED": "projected", "ROLLUP": "sum of sub-budgets", "YEAR_ENDED": "year ended (actual)"}
                         .get(state, PROJ_TEXT.get(state, "")), pr.get("projected") or "",
                         pr.get("difference") or "", (pr.get("difference_pct") or "n/a") if pr.get("difference") else ""]
            if rep["include_next"]:
                n = r["next"]
                line += (["", "—", "", "", ""] if n is None else
                         [n["code"], n["amount"], STATUS_TEXT.get(n["status"], n["status"]), n["change"],
                          n["change_pct"] or "n/a"])
            w.writerow([_csv_safe(v) for v in line])
    return buf.getvalue()


def _entered_text(c: dict) -> str:
    """2.2.0 (#284): how an entered figure is labelled (the status column of a year before PennyWarden)."""
    t = "Entered (sum of sub-budgets)" if c.get("from_sub_budgets") else "Entered"
    if c.get("mismatch"):
        m = c["mismatch"]
        t += f"; sub-budgets add up to {m['budgeted']} budgeted, {m['actual']} actual"
    if c.get("entered_as"):                     # 2.2.0 (#381): called differently that year
        t += f"; as {c['entered_as']}"
    return t


_IND = ParagraphStyle("bp_ind", parent=S["cell"], leftIndent=10)


def _chart(rep: dict, row: dict) -> Drawing:
    labels, bud, act = [], [], []
    for y, c in zip(rep["years"], row["history"]):
        labels.append(y["display_name"])
        bud.append(float(c["budgeted"]) if c else 0)
        act.append(float(c["actual"]) if c else 0)
    labels.append(f"{rep['fiscal_year']['display_name']} (YTD)")
    bud.append(float(row["current"]["budgeted"]))
    act.append(float(row["current"]["actual"]))
    d = Drawing(6.5 * inch, 2.6 * inch)
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 50, 35, 5.2 * inch, 1.8 * inch
    ch.data = [bud, act]
    ch.categoryAxis.categoryNames = labels
    ch.categoryAxis.labels.fontSize = 7
    ch.categoryAxis.labels.fontName = _FONT
    ch.valueAxis.labels.fontSize = 7
    ch.valueAxis.labels.fontName = _FONT
    ch.valueAxis.valueMin = min(0, *bud, *act)
    ch.bars[0].fillColor = branding.color("outline")
    ch.bars[1].fillColor = branding.color("series:0")
    ch.barLabelFormat = "%.0f"
    ch.barLabels.fontSize = 6
    ch.barLabels.fontName = _FONT
    ch.barLabels.nudge = 6
    d.add(ch)
    lg = Legend()
    lg.x, lg.y = 60, 2.45 * inch
    lg.fontSize = 7
    lg.fontName = _FONT
    lg.columnMaximum = 1
    lg.alignment = "right"
    lg.colorNamePairs = [(branding.color("outline"), "Budgeted (left bar)"), (branding.color("series:0"), "Actual (right bar)")]
    d.add(lg)
    d.add(String(0, 0, f"{row['code']} {row['name']}: budgeted and actual per Fiscal Year", fontSize=7, fontName=_FONT))
    return d


_RIGHT = ParagraphStyle("br_right", parent=S["cell"], alignment=2)
_LABEL = ParagraphStyle("br_label", parent=S["cell"], textColor=colors.HexColor("#4a5560"))
S["br_head"] = ParagraphStyle("br_head", parent=S["cell"], alignment=2, textColor=colors.white)   # on_primary (#280)


def _r(text: str) -> object:
    return PM(text, "cell") if not text else Paragraph(text, _RIGHT)


def _diff_short(c: dict | None, key: str = "difference") -> str:
    return escape(diff_text(c, key)) if c else "—"


def _review_columns(rep: dict) -> list[tuple[str, callable]]:
    """#283 (layout A): one column per year, then Avg, the current year (YTD) and the optional Projected and next-year
    columns. Each column gives (Budgeted, Actual, Difference) for a row."""
    cols: list[tuple[str, callable]] = []
    for i, y in enumerate(rep["years"]):
        def cell(r, i=i):
            c = r["history"][i]
            if c is None:
                note = "<i>history on parent</i>" if r["history_note"] else "—"
                return (note, "", "")
            extra = []
            if c.get("source") == "ENTERED":          # 2.2.0 (#284)
                extra.append("<i>entered" + (", sum of sub-budgets" if c.get("from_sub_budgets") else "")
                             + ("; sub-budgets differ" if c.get("mismatch") else "") + "</i>")
                if c.get("entered_as"):               # 2.2.0 (#381): called differently that year
                    extra.append(escape(c["entered_as"]))
            if c.get("renumbered"):
                extra.append(escape(c["code"]))
            if c.get("status") and c["status"] != "APPROVED":
                extra.append(STATUS_TEXT.get(c["status"], c["status"]))
            tail = f"<br/><font size=6>{' · '.join(extra)}</font>" if extra else ""
            return (money(c["budgeted"]) + tail, money(c["actual"]), _diff_short(c))
        cols.append((escape(y["display_name"]) + ("<br/><font size=6>entered</font>" if y.get("entered") else ""),
                     cell))
    if rep["years"]:
        cols.append(("Avg", lambda r: ("—", "", "") if not r.get("average") else
                     (money(r["average"]["budgeted"]), money(r["average"]["actual"]), _diff_short(r["average"]))))
    fyn = rep["fiscal_year"]["display_name"]
    cols.append((f"{escape(fyn)}<br/><font size=6>YTD {_us(rep['as_of'])}</font>",
                 lambda r: (money(r["current"]["budgeted"]), money(r["current"]["actual"]), _diff_short(r["current"]))))
    if rep["projected"]:
        def proj(r):
            pr = r["projection"] or {}
            st = pr.get("state")
            if st in PROJ_TEXT:
                return (money(r["current"]["budgeted"]), f"<i>{PROJ_TEXT[st]}</i>", "")
            word = {"PROJECTED": "projected", "ROLLUP": "sum of sub-budgets", "YEAR_ENDED": "year ended: actual"}.get(st, "")
            return (money(r["current"]["budgeted"]), f"{money(pr['projected'])}<br/><font size=6><i>{word}</i></font>",
                    _diff_short(pr))
        cols.append((f"Projected<br/><font size=6>to {_us(rep['fiscal_year']['end_date'])}</font>", proj))
    if rep["include_next"]:
        nn = rep["next_fiscal_year"]["display_name"] if rep["next_fiscal_year"] else "Next year"

        def nxt(r):
            n = r["next"]
            if n is None:
                return ("—", "", "")
            ch = n["change"]
            word = "no change" if ch in ("0.00", "-0.00") else (
                f"{'+' if not ch.startswith('-') else '−'}{money(ch.lstrip('-'))} "
                f"({'n/a' if n['change_pct'] is None else n['change_pct'].lstrip('-') + '%'}) vs this year")
            return (f"{money(n['amount'])}<br/><font size=6>{escape(n['code'])} · "
                    f"{STATUS_TEXT.get(n['status'], n['status'])}</font>", "", escape(word))
        cols.append((f"{escape(nn)}<br/><font size=6>next year's budget</font>", nxt))
    return cols


def _review_flowables(db: Session, ctx, rep: dict, doc) -> list:
    """The Budget Review pages (layout A, #283): a block per budget - its heading, then Budgeted, Actual and
    Difference with the years across - in an Income and an Expense section."""
    ws = db.get(Workspace, ctx.workspace_id)
    fyn = rep["fiscal_year"]["display_name"]
    frame_w = doc.pagesize[0] - 2 * MARGIN - 12
    label_w, min_col = 0.95 * inch, 1.0 * inch
    cols = _review_columns(rep)
    per_band = max(1, int((frame_w - label_w) // min_col))
    bands = [cols[i:i + per_band] for i in range(0, len(cols), per_band)]
    band = Table([[Paragraph(f"<b>{escape(ws.name)}</b>", ParagraphStyle("brb", parent=S["body"], textColor=branding.color("on_primary"))),
                   Paragraph(f"<b>Budget Review — {escape(fyn)}</b>", ParagraphStyle("brt", parent=S["body"], alignment=2,
                                                                                    textColor=branding.color("on_primary")))]],
                 colWidths=[frame_w / 2, frame_w / 2])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), branding.color("primary")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                              ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
    f: list = [_Mark(doc, "Budget Review"), band, Spacer(1, 6),
               PM(f"Fiscal Year <b>{escape(fyn)}</b> ({_us(rep['fiscal_year']['start_date'])} to "
                  f"{_us(rep['fiscal_year']['end_date'])}). Actuals year-to-date as of {_us(rep['as_of'])}. "
                  f"Prior years shown: {len(rep['years'])} of {rep['available_years']}.", "body"), Spacer(1, 4)]
    notes = ["Difference = actual − budgeted, marked over or under; n/a when nothing was budgeted. Avg = the average of "
             "the prior years shown in which the budget existed (the current year is not included). Actuals are ACTIVE "
             "transactions only, as on the Budgets page; a budget's actual includes its sub-budgets.",
             "History follows the budget continuation links, so a renumbered budget stays on one line (its earlier code "
             "is printed under that year's amount). — means no linked budget that year."]
    if any(y.get("entered") for y in rep["years"]):
        notes.append("Years marked “entered” are before the first Fiscal Year in PennyWarden: their figures were entered "
                     "by a Budget Manager from earlier records (a parent without its own figures shows the sum of its "
                     "sub-budgets'). They are not PennyWarden transactions.")
    if rep["projected"]:
        pb = rep["projection_basis"]
        notes.append("Projected = YTD ÷ elapsed months × months in the Fiscal Year "
                     f"({pb['elapsed_months']} of {pb['months']} months elapsed). Projected figures are estimates; "
                     "budgets marked “Complete: no projection” were left unprojected by the person running the report.")
    f += [P(n, "small") for n in notes] + [Spacer(1, 6)]
    for sec in ("income", "expense"):
        rows = rep[sec]
        if not rows:
            continue
        f.append(CondPageBreak(1.6 * inch))
        f.append(PM(sec.title(), "h2"))
        for bi, bcols in enumerate(bands):
            if len(bands) > 1:
                f.append(P(f"Columns {bi + 1} of {len(bands)}", "small"))
            cw = min(1.35 * inch, (frame_w - label_w) / len(bcols))
            n = len(bcols) + 1
            head = [Paragraph("", S["br_head"])] + [Paragraph(f"<b>{h}</b>", S["br_head"]) for h, _fn in bcols]
            data, style = [head], [("BACKGROUND", (0, 0), (-1, 0), branding.color("primary")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                                   ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
            for r in rows:
                status = "" if r["status"] == "APPROVED" else f" <font size=6>({STATUS_TEXT.get(r['status'], r['status'])})</font>"
                label = f"{escape(r['code'])} {escape(r['name'])}{status}"
                i = len(data)
                data.append([Paragraph(f"<b>{label}</b>" if r["level"] == "parent" else "&nbsp;&nbsp;&nbsp;" + label,
                                       S["cell"])] + [""] * (n - 1))
                style += [("SPAN", (0, i), (-1, i)), ("BACKGROUND", (0, i), (-1, i), branding.color("surface_variant" if r["level"] == "parent" else "surface")),
                          ("LINEABOVE", (0, i), (-1, i), 0.4, colors.HexColor("#9aa3ad"))]
                vals = [fn(r) for _h, fn in bcols]
                for k, word in enumerate(("Budgeted", "Actual", "Difference")):
                    data.append([Paragraph(word, _LABEL)] + [_r(v[k]) for v in vals])
                style += [("LINEBELOW", (1, i + 3), (-1, i + 3), 0.25, colors.HexColor("#d5dbe1")),
                          ("NOSPLIT", (0, i), (-1, i + 3))]           # a budget's block stays on one page
            t = Table(data, colWidths=[label_w] + [cw] * len(bcols), repeatRows=1, hAlign="LEFT")
            t.setStyle(TableStyle(style))
            f += [t, gross_note(), Spacer(1, 8)]   # 2.3.0 (#371)
    if rep["filter"]["budget_id"] is not None:
        row = (rep["income"] + rep["expense"])[0]
        f += [KeepTogether([PM("Budgeted and actual per year", "h2"), _chart(rep, row), gross_note()])]
    f += [Spacer(1, 8), P(f"Generated {utcnow():%Y-%m-%d %H:%M} UTC by {ctx.user.username} — {ws.name}", "small")]
    return f


@branding.themed
def budget_review_pdf(db: Session, ctx, rep: dict) -> tuple[str, str, int]:
    ws = db.get(Workspace, ctx.workspace_id)
    fyn = rep["fiscal_year"]["display_name"]
    title = f"{ws.name}  ·  Budget Review — {fyn}  ·  printed {_us(dt.date.today())}"
    buf = io.BytesIO()
    doc = _AuditDoc(buf, pagesize=landscape(letter), title="Budget Review", author=ws.name)
    doc.build(_review_flowables(db, ctx, rep, doc))
    fd, path = tempfile.mkstemp(prefix="fmpoc-budget-review-", suffix=".pdf")
    os.close(fd)
    try:
        pages = _stamp_and_write(buf.getvalue(), doc, path, title)
    except Exception:
        os.unlink(path)
        raise
    return path, f"budget-review-{_safe(fyn)}.pdf", pages


# 2.1.0 (#283): the report was called Budget Prep (#257); the old names stay for callers
budget_prep, budget_prep_csv, budget_prep_pdf = budget_review, budget_review_csv, budget_review_pdf


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s).strip("-")[:60] or "fiscal-year"


# ------------------------------------------------------------------ Fiscal Year Planning Sheet (#261)
PLAN_BLANK_ROWS = 4
PLAN_PAGE2_ROWS = 12
_HIDDEN = ("REJECTED", "INACTIVE", "DELETED")


def _draft_next(db: Session, ws_id: int, fy: FiscalYear) -> FiscalYear | None:
    _prior, nxt = adjacent_years(db, ws_id, fy)
    return nxt if nxt is not None and nxt.status == "DRAFT" else None


def planning_context(db: Session, ws_id: int) -> tuple[FiscalYear, FiscalYear | None]:
    """Build 3 feedback (2026-10-20): the sheet is printed from the Fiscal Years page, often before next year exists.
    One planning at a time:
    - a Draft Fiscal Year with an earlier year -> plan that draft from the year before it (the latest such draft);
    - otherwise the year covering today (not a draft), else the latest year that isn't a draft, else the latest year.
    """
    fys = list(db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id).order_by(FiscalYear.start_date)))
    if not fys:
        raise validation("Create a Fiscal Year first: the sheet lists its budgets.", "fiscal_year_id")
    for d in reversed([f for f in fys if f.status == "DRAFT"]):
        earlier = [f for f in fys if f.start_date < d.start_date]
        if earlier:
            return earlier[-1], d
    today = dt.date.today()
    cover = [f for f in fys if f.start_date <= today <= f.end_date and f.status != "DRAFT"]
    if cover:
        return cover[-1], None
    settled = [f for f in fys if f.status != "DRAFT"]
    return (settled or fys)[-1], None


def planning_context_out(db: Session, ws_id: int) -> dict:
    base, draft = planning_context(db, ws_id)
    return {"fiscal_year": fy_brief(base), "draft_fiscal_year": fy_brief(draft) if draft else None}


def planning_rows(db: Session, ctx, fy: FiscalYear, as_of: dt.date, draft: FiscalYear | None = None,
                  auto: bool = False) -> dict:
    """The rows of the sheet: {"income": [...], "expense": [...], "draft": FiscalYear|None}. A row: code, previous_code
    (when the draft renumbered it), name, level, status, budgeted/ytd/projection (None for a new draft budget),
    proposed (draft amount or None), not_in_draft."""
    struct = structure(db, fy)
    ch = choices(db, ctx, fy, struct)
    bas = basis(fy, as_of)
    all_ids = [b.id for b in db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id))]
    ytd = active_allocation_totals(db, all_ids, None, as_of)
    if not auto:
        draft = _draft_next(db, ctx.workspace_id, fy)
    dstruct = structure(db, draft) if draft else {"INCOME": [], "EXPENSE": []}
    matched: set[int] = set()

    def proj(b: Budget, y: int) -> tuple[str, int]:
        if not ch[b.id]["project"]:
            return "COMPLETE", y
        v = project(y, bas)
        return ("TOO_EARLY", y) if v is None else ("VALUE", v)

    def succ(b: Budget) -> Budget | None:
        if draft is None:
            return None
        n = _successor(db, b, draft)
        return n if n is not None and n.status not in _HIDDEN else None

    def row(b: Budget, parent: Budget | None, level: str, projection, y) -> dict:
        code = budget_display_code(b, parent)
        n = succ(b)
        r = {"budget_id": b.id, "code": code, "previous_code": None, "name": b.name, "level": level, "status": b.status,
             "budgeted": b.amount_cents, "ytd": y, "projection": projection, "proposed": None,
             "draft_budget_id": None, "not_in_draft": draft is not None and n is None, "new": False}
        if b.is_other and parent is not None and succ(parent) is not None:
            r["not_in_draft"] = False     # the parent continues; its amount is on the parent's row
        if n is not None:
            matched.add(n.id)
            ncode = _code(db, n)
            r.update(proposed=n.amount_cents, draft_budget_id=n.id, name=n.name if n.name else b.name)
            if ncode != code:
                r.update(code=ncode, previous_code=code)
        return r

    def new_row(b: Budget, parent: Budget | None, level: str) -> dict:
        matched.add(b.id)
        return {"budget_id": None, "code": budget_display_code(b, parent), "previous_code": None, "name": b.name,
                "level": level, "status": b.status, "budgeted": None, "ytd": None, "projection": None,
                "proposed": b.amount_cents, "draft_budget_id": b.id, "not_in_draft": False, "new": True}

    out: dict[str, list] = {}
    for key, rows in struct.items():
        lines = []
        for r in rows:
            p = r["budget"]
            if p.status in _HIDDEN:
                continue
            fam = [p.id] + [k.id for k in _kids(db, p.id)]
            p_ytd = sum(ytd.get(i, 0) for i in fam)
            kids = [k for k in r["children"] if k.status not in _HIDDEN]
            kid_rows, roll, early = [], 0, False
            for k in kids:
                st, v = proj(k, ytd.get(k.id, 0))
                early |= st == "TOO_EARLY"
                roll += v
                kid_rows.append(row(k, p, "sub", (st, v), ytd.get(k.id, 0)))
            if r["children"]:
                rest = p_ytd - sum(ytd.get(k.id, 0) for k in kids)
                pp = ("TOO_EARLY", p_ytd) if early and bas["state"] == "TOO_EARLY" else ("VALUE", roll + rest)
            else:
                pp = proj(p, p_ytd)
            prow = row(p, None, "parent", pp, p_ytd)
            lines.append(prow)
            lines += kid_rows
            # draft sub-budgets under this parent's draft continuation that continue nothing here
            if prow["draft_budget_id"]:
                dp = db.get(Budget, prow["draft_budget_id"])
                drow = next((x for x in dstruct[key] if x["budget"].id == dp.id), None)
                for dk in (drow["children"] if drow else []):
                    if dk.id not in matched and dk.status not in _HIDDEN and not _continues_listed(dk, kids):
                        lines.append(new_row(dk, dp, "sub"))
        # draft budgets with no current-year predecessor
        for dr in dstruct[key]:
            dp = dr["budget"]
            if dp.status in _HIDDEN:
                continue
            if dp.id not in matched:
                lines.append(new_row(dp, None, "parent"))
                for dk in dr["children"]:
                    if dk.id not in matched and dk.status not in _HIDDEN:
                        lines.append(new_row(dk, dp, "sub"))
        out[key.lower()] = lines
    # a draft sub-budget continuing a current sub-budget under another parent was matched there; anything left over
    return {**out, "draft": draft, "basis": bas}


def _continues_listed(dk: Budget, kids: list[Budget]) -> bool:
    return dk.continues_budget_id is not None and any(k.id == dk.continues_budget_id for k in kids)


def _plan_table(rows: list[dict], heads: list[str], widths: list[float], blank: int, revision: bool, ytd_head: str):
    data = [[PM(f"<b>{h}</b>", "cell") for h in heads]]
    for r in rows:
        style = _IND if r["level"] == "sub" else S["cell"]
        code = escape(r["code"]) + (f"<br/><font size=6>was {escape(r['previous_code'])}</font>" if r["previous_code"] else "")
        bits = []
        if r["status"] == "DRAFT" and not r["new"]:
            bits.append("Draft")
        if r["not_in_draft"]:
            bits.append("<b>not in draft</b>")
        if r["new"]:
            bits.append("new in draft")
        name = escape(r["name"]) + (f" <font size=6>({' · '.join(bits)})</font>" if bits else "")
        if r["level"] == "parent":
            name = f"<b>{escape(r['name'])}</b>" + (f" <font size=6>({' · '.join(bits)})</font>" if bits else "")
        if r["projection"] is None:
            pj = ""
        else:
            st, v = r["projection"]
            pj = {"COMPLETE": "Complete", "TOO_EARLY": "too early"}.get(st) or money(v)
        line = [Paragraph(code, S["cell"]), Paragraph(name, style),
                P(money(r["budgeted"]) if r["budgeted"] is not None else "", "cellr"),
                P(money(r["ytd"]) if r["ytd"] is not None else "", "cellr"), P(pj, "cellr"),
                P(money(r["proposed"]) if r["proposed"] is not None else "", "cellr")]
        if revision:
            line.append("")
        data.append(line)
    data += [[""] * len(heads) for _ in range(blank)]
    heights = [None] + [0.27 * inch] * (len(data) - 1)
    t = Table(data, colWidths=widths, repeatRows=1, rowHeights=heights)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#6b7480")),
                           ("BACKGROUND", (0, 0), (-1, 0), branding.color("surface_variant")),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("VALIGN", (0, 0), (-1, 0), "BOTTOM"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return t


@branding.themed
def planning_sheet(db: Session, ctx, fy: FiscalYear | None, as_of: dt.date | None = None) -> tuple[str, str, dict]:
    """fy None: the year being planned is worked out (planning_context)."""
    auto_draft, auto = None, fy is None
    if fy is None:
        fy, auto_draft = planning_context(db, ctx.workspace_id)
    as_of = as_of or dt.date.today()
    ws = db.get(Workspace, ctx.workspace_id)
    data = planning_rows(db, ctx, fy, as_of, auto_draft, auto)
    draft = data["draft"]
    revision = draft is not None
    printed = _us(dt.date.today())
    title = f"{ws.name}  ·  Fiscal Year Planning Sheet  ·  printed {printed}"
    ytd_head = f"Actual YTD as of {_us(as_of)}"
    heads = ["Budget Code", "Budget Description", "Previous Budgeted", ytd_head, "Projected", "Proposed Budget"]
    if revision:
        heads.append("Proposed Revision")
        widths = [0.72 * inch, 1.98 * inch] + [0.88 * inch] * 5
    else:
        widths = [0.8 * inch, 2.4 * inch] + [1.0 * inch] * 4
    buf = io.BytesIO()
    doc = _AuditDoc(buf, title="Fiscal Year Planning Sheet", author=ws.name)
    frame_w = letter[0] - 2 * MARGIN - 12
    left = [PM(f"<b>{escape(ws.name)}</b>", "metav"), PM("Fiscal Year Planning Sheet", "h1")]
    head = Table([[left, PM("Meeting date: ____________________", "metav")]],
                 colWidths=[frame_w - 2.6 * inch, 2.6 * inch])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    cur = (f"Current Fiscal Year: <b>{escape(fy.display_name)}</b> ({_us(fy.start_date)} to {_us(fy.end_date)})")
    if draft is not None:
        new = (f"New Fiscal Year: <b>{escape(draft.display_name)}</b> ({_us(draft.start_date)} to {_us(draft.end_date)}) "
               "<font size=7>— Draft</font>")
    else:
        new = "New Fiscal Year: ______________________________ &nbsp; Dates: ______________ to ______________"
    att = Table([[PM("Attendees:", "metav"), PM("_" * 38, "metav"), PM("_" * 38, "metav")]]
                + [["", PM("_" * 38, "metav"), PM("_" * 38, "metav")] for _ in range(2)],
                colWidths=[0.9 * inch, (frame_w - 0.9 * inch) / 2, (frame_w - 0.9 * inch) / 2],
                rowHeights=[0.3 * inch] * 3)
    att.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    proj_note = ("Projected: average monthly activity so far carried to the Fiscal Year end; “Complete” = not projected "
                 "(a budget known to be finished)." if data["basis"]["state"] != "TOO_EARLY" else
                 "Projected: less than one month of the Fiscal Year has elapsed - too early to project.")
    proposed_note = (" Proposed Budget shows the amount already in the Draft; write changes in Proposed Revision."
                     if revision else " Write the proposed amount in Proposed Budget.")
    f: list = [_Mark(doc, "Budgets"), head, Spacer(1, 2), PM(cur, "metav"), PM(new, "metav"), Spacer(1, 2), att,
               Spacer(1, 4), P(proj_note + proposed_note + " Previous columns are the current Fiscal Year.", "small"),
               Spacer(1, 4)]
    for i, key in enumerate(("income", "expense")):
        if i:   # a table that would start in the bottom 35% of the page starts on a new page (Kyle, 2026-10-20)
            f.append(CondPageBreak(0.35 * BODY_H))
        f += [PM(key.title(), "h2"),
              _plan_table(data[key], heads, widths, PLAN_BLANK_ROWS, revision, ytd_head), gross_note(), Spacer(1, 8)]
    f.append(P("After the meeting the filled-in sheet can be scanned and attached to the new Fiscal Year as an Other "
               "document. It is not a required document for the Fiscal Year closure review.", "small"))
    # the blank tables always come last
    f += [PageBreak(), _Mark(doc, "Additional new budgets"), PM("Additional new budgets", "h1"),
          PM(f"{escape(ws.name)} — Fiscal Year Planning Sheet", "metav"), Spacer(1, 6)]
    blank_heads = ["Budget Code", "Budget Description", "Proposed Budget"] + (["Proposed Revision"] if revision else [])
    bw = [0.9 * inch, frame_w - 0.9 * inch - 1.25 * inch * (len(blank_heads) - 2)] + [1.25 * inch] * (len(blank_heads) - 2)
    for key in ("Income", "Expense"):
        t = Table([[PM(f"<b>{h}</b>", "cell") for h in blank_heads]] + [[""] * len(blank_heads)] * PLAN_PAGE2_ROWS,
                  colWidths=bw, rowHeights=[None] + [0.3 * inch] * PLAN_PAGE2_ROWS)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#6b7480")),
                               ("BACKGROUND", (0, 0), (-1, 0), branding.color("surface_variant"))]))
        f += [PM(key, "h2"), t, Spacer(1, 10)]
    doc.build(f)
    fd, path = tempfile.mkstemp(prefix="fmpoc-planning-", suffix=".pdf")
    os.close(fd)
    try:
        pages = _stamp_and_write(buf.getvalue(), doc, path, title)
    except Exception:
        os.unlink(path)
        raise
    summary = {"report": "PLANNING_SHEET", "fiscal_year_id": fy.id, "as_of": as_of.isoformat(),
               "draft_fiscal_year_id": draft.id if draft else None, "pages": pages,
               "rows": len(data["income"]) + len(data["expense"])}
    return path, f"planning-sheet-{_safe(fy.display_name)}.pdf", summary


@branding.themed
def append_review(db: Session, ctx, sheet_path: str, summary: dict, as_of: dt.date | None) -> tuple[str, dict]:
    """2.1.0 (#283): the Planning Sheet with the Budget Review of the same year appended (last 3 years, projected with
    the person's projection choices, and the Draft year's budgets when there is one). Each part keeps its own page
    numbers. Returns the new file and the summary with the review's details."""
    from pypdf import PdfReader, PdfWriter
    fy = db.get(FiscalYear, summary["fiscal_year_id"])
    draft = _draft_next(db, ctx.workspace_id, fy)
    rep = budget_review(db, ctx, fy, years=3, projected=True, include_next=draft is not None, as_of=as_of)
    review_path, _name, pages = budget_review_pdf(db, ctx, rep)
    fd, out = tempfile.mkstemp(prefix="fmpoc-planning-review-", suffix=".pdf")
    os.close(fd)
    try:
        w = PdfWriter()
        for part in (sheet_path, review_path):
            for page in PdfReader(part).pages:
                w.add_page(page)
        w.add_metadata({"/Title": "Fiscal Year Planning Sheet and Budget Review", "/Creator": "PennyWarden"})
        with open(out, "wb") as fh:
            w.write(fh)
    finally:
        for part in (sheet_path, review_path):
            if os.path.exists(part):
                os.unlink(part)
    return out, {**summary, "include_review": True, "review_pages": pages, "review_years": len(rep["years"])}
