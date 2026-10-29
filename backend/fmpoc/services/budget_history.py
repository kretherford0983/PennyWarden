"""2.2.0 (#284, #381): budget history before PennyWarden.

A Budget Manager enters the **budgeted and actual figures of years before the first Fiscal Year in PennyWarden** (from
the old spreadsheets), so a budget's History, the Budget Review and the Planning Sheet's appended review show the full
history.

#381 (Kyle, 2026-10-28) - **budgets from before PennyWarden ("former budgets")**:

1. **Unified storage.** Every entered figure belongs to a *former budget*: one line of the old spreadsheets (code,
   name, Income/Expense). A PennyWarden budget reaches those years only through an explicit link
   (`Budget.continues_former_budget_id`), set on the earliest budget of its line (the #89 links). *Add an earlier
   year* on a budget's History creates (or reuses) the former budget its line continues, so the normal case looks the
   same as #284. A wrong match is fixed by unlinking; nothing is moved or re-entered.
2. **Links may cross levels and never go by code.** Any budget or sub-budget of the same type may continue a former
   budget (old flat 101 -> 100-01). At most one budget continues a former budget; a budget continues one predecessor
   (an earlier PennyWarden budget or a former budget).
3. **Other may continue a former budget** (only a former budget: between PennyWarden years Other follows its parent's
   line). In the old spreadsheets uncategorized amounts sat on the parent row itself, which is PennyWarden's -00 Other.
4. **CSV import** creates former budgets, their years and the links in one pass: *budget code* (a budget of the chosen
   Fiscal Year, -00 for Other; blank = a former budget nothing continues), *type*, *former code*, *former name*,
   *year*, *budgeted*, *actual*, *note*, optional *line*. Previewed before anything is saved.
5. **Rows form one line** by budget code; with a blank budget code by former code; the *line* column overrides.
6. **Each year keeps the code and name it had** (an entry's `code`/`name`, empty = the former budget's); the former
   budget is shown under its most recent ones.

Kept from #284: a parent without its own figure shows the sum of its sub-budgets' (and its Other's), a mismatch note
when both differ; years in PennyWarden refused (an entry later covered by a Fiscal Year is kept but no longer counted);
reporting only (BR-048); never deleted (BR-001): corrected or retired, with a reason; every change audited.
"""
from __future__ import annotations

import csv
import io
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, conflict, not_found, validation
from ..models import Budget, BudgetHistoryEntry, FiscalYear, FormerBudget, utcnow
from ..money import fmt, parse_amount
from .common import budget_display_code, fy_brief
from .fundraiser_series import fy_year, label_year

MAX_CSV_ROWS = 2000
MAX_CSV_BYTES = 512 * 1024
CSV_COLUMNS = ["budget code", "budget name (ignored)", "type", "former code", "former name", "year", "budgeted",
               "actual", "note", "line"]
REQUIRED_COLUMNS = ["year", "budgeted", "actual"]
_TYPES = {"income": "INCOME", "expense": "EXPENSE", "i": "INCOME", "e": "EXPENSE"}


# ------------------------------------------------------------------ years
def first_year(db: Session, ws_id: int) -> int | None:
    """The year of the first Fiscal Year in PennyWarden (None: no Fiscal Year yet)."""
    years = [fy_year(f) for f in db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id))]
    return min(years) if years else None


def _year_of(db: Session, ws_id: int, label: str) -> int:
    year = label_year(label)
    if year is None:
        raise validation("Include the year in the Fiscal Year label, for example FY2021.", "fiscal_year_label")
    first = first_year(db, ws_id)
    if first is not None and year >= first:
        raise AppError(409, "YEAR_IN_PENNYWARDEN", f"{label}: only years before the first Fiscal Year in PennyWarden "
                       f"(FY{first}) can be entered; that year's figures come from PennyWarden.")
    return year


def _cents(v, field: str, allow_negative: bool) -> int:
    if v is None or str(v).strip() == "":
        raise validation("This amount is required.", field)
    try:
        return parse_amount(str(v).strip().replace("$", "").replace(",", ""), allow_negative=allow_negative,
                            allow_zero=True)
    except ValueError as e:
        raise validation(str(e).capitalize() + ".", field) from None


# ------------------------------------------------------------------ lines
def pw_line(db: Session, b: Budget) -> list[Budget]:
    """The budget and every earlier budget it continues (#89), newest first."""
    out, seen, cur = [b], {b.id}, b
    while cur.continues_budget_id and cur.continues_budget_id not in seen:
        cur = db.get(Budget, cur.continues_budget_id)
        if cur is None:
            break
        out.append(cur)
        seen.add(cur.id)
    return out


def _other_of(db: Session, parent: Budget) -> Budget | None:
    return db.scalar(select(Budget).where(Budget.parent_budget_id == parent.id, Budget.is_other.is_(True)).limit(1))


def line_budgets(db: Session, b: Budget) -> list[Budget]:
    """b and the earlier PennyWarden budgets of its line, newest first. Other has no link of its own between
    PennyWarden years: its line is the Other of each budget of its parent's line."""
    if b.is_other and b.parent_budget_id:
        out = []
        for p in pw_line(db, db.get(Budget, b.parent_budget_id)):
            o = b if p.id == b.parent_budget_id else _other_of(db, p)
            if o is not None:
                out.append(o)
        return out
    return pw_line(db, b)


def link_holder(db: Session, b: Budget) -> Budget:
    """The budget of b's line that carries (or would carry) the link to a former budget: the earliest."""
    return line_budgets(db, b)[-1]


def former_of(db: Session, b: Budget) -> FormerBudget | None:
    """The former budget b's line continues (None: none, or b is Budget 0)."""
    if b.is_budget_zero:
        return None
    for x in line_budgets(db, b):
        if x.continues_former_budget_id:
            f = db.get(FormerBudget, x.continues_former_budget_id)
            return f if f is not None and f.retired_at is None and f.workspace_id == b.workspace_id else None
    return None


def continued_by(db: Session, f: FormerBudget, except_id: int | None = None) -> Budget | None:
    q = select(Budget).where(Budget.continues_former_budget_id == f.id, Budget.status != "DELETED")
    if except_id is not None:
        q = q.where(Budget.id != except_id)
    return db.scalar(q.limit(1))


def _sub_formers(db: Session, parent: Budget) -> list[FormerBudget]:
    """The former budgets of the lines of a parent's sub-budgets and its Other (over the parent's whole line)."""
    seen: set[int] = set()
    out: list[FormerBudget] = []
    for p in pw_line(db, parent):
        for k in db.scalars(select(Budget).where(Budget.parent_budget_id == p.id, Budget.status != "DELETED",
                                                 Budget.is_budget_zero.is_(False))):
            if k.id in seen:
                continue
            seen.update(x.id for x in line_budgets(db, k))
            f = former_of(db, k)
            if f is not None and all(f.id != x.id for x in out):
                out.append(f)
    return out


def _entries(db: Session, former_ids: list[int], retired: bool = False) -> list[BudgetHistoryEntry]:
    if not former_ids:
        return []
    q = select(BudgetHistoryEntry).where(BudgetHistoryEntry.former_budget_id.in_(former_ids))
    if not retired:
        q = q.where(BudgetHistoryEntry.retired_at.is_(None))
    return list(db.scalars(q.order_by(BudgetHistoryEntry.year, BudgetHistoryEntry.id)))


# ------------------------------------------------------------------ outputs
def current_label(db: Session, f: FormerBudget) -> tuple[str, str]:
    """Decision 6: a former budget is shown under the code and name of its most recent year."""
    e = db.scalar(select(BudgetHistoryEntry).where(BudgetHistoryEntry.former_budget_id == f.id,
                                                   BudgetHistoryEntry.retired_at.is_(None))
                  .order_by(BudgetHistoryEntry.year.desc(), BudgetHistoryEntry.id.desc()).limit(1))
    return (e.code or f.code, e.name or f.name) if e is not None else (f.code, f.name)


def budget_brief(db: Session, b: Budget) -> dict:
    parent = db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None
    fy = db.get(FiscalYear, b.fiscal_year_id)
    code = budget_display_code(b, parent)
    return {"id": b.id, "fiscal_year": fy_brief(fy), "code": code, "name": b.name, "is_other": b.is_other,
            "budget_type": b.budget_type, "status": b.status, "label": f"{fy.display_name} {code} {b.name}"}


def former_brief(db: Session, f: FormerBudget | None) -> dict | None:
    if f is None:
        return None
    code, name = current_label(db, f)
    return {"id": f.id, "code": code, "name": name, "label": f"{code} {name}", "budget_type": f.budget_type,
            "retired": f.retired_at is not None}


def former_out(db: Session, f: FormerBudget, first: int | None = None) -> dict:
    active = _entries(db, [f.id])
    by = continued_by(db, f)
    return {**former_brief(db, f), "default_code": f.code, "default_name": f.name, "note": f.note,
            "retired_at": f.retired_at.isoformat(timespec="seconds") + "Z" if f.retired_at else None,
            "retire_reason": f.retire_reason, "years": len(active),
            "first_year_entered": active[0].fiscal_year_label if active else None,
            "last_year_entered": active[-1].fiscal_year_label if active else None,
            "budgeted_total": fmt(sum(e.budgeted_cents for e in active)),
            "actual_total": fmt(sum(e.actual_cents for e in active)),
            "continued_by": budget_brief(db, by) if by is not None else None}


def entry_out(e: BudgetHistoryEntry, f: FormerBudget | None = None) -> dict:
    out = {"id": e.id, "former_budget_id": e.former_budget_id, "budget_id": e.budget_id,
           "fiscal_year_label": e.fiscal_year_label, "year": e.year, "code": e.code, "name": e.name,
           "budgeted": fmt(e.budgeted_cents), "actual": fmt(e.actual_cents), "note": e.note,
           "retired": e.retired_at is not None,
           "retired_at": e.retired_at.isoformat(timespec="seconds") + "Z" if e.retired_at else None,
           "retire_reason": e.retire_reason}
    if f is not None:
        out["code_shown"], out["name_shown"] = e.code or f.code, e.name or f.name
    return out


# ------------------------------------------------------------------ figures for reports
def figures(db: Session, b: Budget, first: int | None) -> dict[int, dict]:
    """year -> the entered figure shown for budget `b` (only years before the first Fiscal Year in PennyWarden):
    {label, budgeted (cents), actual (cents), source: own|subs, mismatch: None|{budgeted, actual} (sum of subs),
    code/name: what the budget was called that year (own figures)}."""
    if b.is_budget_zero:
        return {}
    f = former_of(db, b)
    own = {e.year: e for e in _entries(db, [f.id])} if f is not None else {}
    subs: dict[int, dict] = {}
    if b.parent_budget_id is None:
        for sf in _sub_formers(db, b):
            if f is not None and sf.id == f.id:
                continue
            for e in _entries(db, [sf.id]):
                s = subs.setdefault(e.year, {"budgeted": 0, "actual": 0, "labels": []})
                s["budgeted"] += e.budgeted_cents
                s["actual"] += e.actual_cents
                s["labels"].append(e.fiscal_year_label)
    out: dict[int, dict] = {}
    for y in set(own) | set(subs):
        if first is not None and y >= first:
            continue
        if y in own:
            e, s = own[y], subs.get(y)
            mismatch = ({"budgeted": fmt(s["budgeted"]), "actual": fmt(s["actual"])}
                        if s and (s["budgeted"] != e.budgeted_cents or s["actual"] != e.actual_cents) else None)
            out[y] = {"label": e.fiscal_year_label, "budgeted": e.budgeted_cents, "actual": e.actual_cents,
                      "source": "own", "entry_id": e.id, "note": e.note, "mismatch": mismatch,
                      "code": e.code or f.code, "name": e.name or f.name}
        else:
            s = subs[y]
            out[y] = {"label": s["labels"][0], "budgeted": s["budgeted"], "actual": s["actual"], "source": "subs",
                      "entry_id": None, "note": None, "mismatch": None, "code": None, "name": None}
    return out


def year_labels(db: Session, ws_id: int, first: int | None, all_formers: bool = False) -> dict[int, str]:
    """year -> column heading for every entered year before the first Fiscal Year (the label most often used), of the
    former budgets a budget continues (one nothing continues adds no empty column to a Fiscal Year's review).
    2.3.0 (#382): `all_formers` - every former budget, for the review that also lists budgets not in the chosen year."""
    linked = select(Budget.continues_former_budget_id).where(Budget.workspace_id == ws_id, Budget.status != "DELETED",
                                                             Budget.continues_former_budget_id.is_not(None))
    q = (select(BudgetHistoryEntry).join(FormerBudget, FormerBudget.id == BudgetHistoryEntry.former_budget_id)
         .where(BudgetHistoryEntry.workspace_id == ws_id, BudgetHistoryEntry.retired_at.is_(None),
                FormerBudget.retired_at.is_(None)))
    if not all_formers:
        q = q.where(FormerBudget.id.in_(linked))
    counts: dict[int, dict[str, int]] = {}
    for e in db.scalars(q):
        if first is not None and e.year >= first:
            continue
        c = counts.setdefault(e.year, {})
        c[e.fiscal_year_label] = c.get(e.fiscal_year_label, 0) + 1
    return {y: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for y, c in counts.items()}


def has_entries(db: Session, b: Budget) -> bool:
    if b.is_budget_zero:
        return False
    formers = [f] if (f := former_of(db, b)) is not None else []
    if b.parent_budget_id is None:
        formers += _sub_formers(db, b)
    return bool(_entries(db, [x.id for x in formers]))


# ------------------------------------------------------------------ the History view
def view(db: Session, ctx, b: Budget) -> dict:
    """The entered years of a budget's line for its History view: its former budget's entries (retired ones too,
    marked), and for a parent the years filled only by its sub-budgets' entries; the former budget it continues and
    the budget of its line that carries the link."""
    first = first_year(db, ctx.workspace_id)
    f = former_of(db, b)
    holder = link_holder(db, b)
    if f is not None:
        holder = next((x for x in line_budgets(db, b) if x.continues_former_budget_id == f.id), holder)
    own = _entries(db, [f.id], retired=True) if f is not None else []
    shown = figures(db, b, first)
    rows = []
    for e in own:
        fig = shown.get(e.year) if e.retired_at is None else None
        rows.append({**entry_out(e, f), "source": "ENTERED", "from_sub_budgets": False,
                     "counted": e.retired_at is None and (first is None or e.year < first),
                     "mismatch": fig["mismatch"] if fig and fig.get("entry_id") == e.id else None})
    for y, fig in sorted(shown.items()):
        if fig["source"] == "subs":
            rows.append({"id": None, "former_budget_id": None, "budget_id": None, "fiscal_year_label": fig["label"],
                         "year": y, "code": None, "name": None, "code_shown": None, "name_shown": None,
                         "budgeted": fmt(fig["budgeted"]), "actual": fmt(fig["actual"]), "note": None,
                         "retired": False, "retired_at": None, "retire_reason": None, "source": "ENTERED",
                         "from_sub_budgets": True, "counted": True, "mismatch": None})
    rows.sort(key=lambda r: (r["year"], r["from_sub_budgets"], r["id"] or 0))
    return {"first_year": first, "can_enter": not b.is_budget_zero and b.status != "DELETED", "entries": rows,
            "former": former_out(db, f, first) if f is not None else None,
            "holder": budget_brief(db, holder), "is_holder": holder.id == b.id}


# ------------------------------------------------------------------ former budgets
def get_former(db: Session, ctx, former_id: int) -> FormerBudget:
    f = db.get(FormerBudget, former_id) if isinstance(former_id, int) else None
    if f is None or f.workspace_id != ctx.workspace_id:
        raise not_found("Budget from before PennyWarden")
    return f


def _snap(f: FormerBudget) -> dict:
    return {"id": f.id, "code": f.code, "name": f.name, "budget_type": f.budget_type, "note": f.note,
            "retired": f.retired_at is not None, "retire_reason": f.retire_reason}


def _clean(v: str | None, size: int) -> str | None:
    v = (v or "").strip()[:size]
    return v or None


def _create_former(db: Session, ctx, code: str, name: str, budget_type: str, note: str | None = None,
                   via: str = "single") -> FormerBudget:
    code, name = _clean(code, 20), _clean(name, 120)
    if not code:
        raise validation("A code is required.", "code")
    if budget_type not in ("INCOME", "EXPENSE"):
        raise validation("Type must be Income or Expense.", "budget_type")
    f = FormerBudget(workspace_id=ctx.workspace_id, code=code, name=name or code, budget_type=budget_type,
                     note=_clean(note, 500), created_by_user_id=ctx.user.id)
    db.add(f)
    db.flush()
    audit.record(db, ctx, "FORMER_BUDGET_CREATED", "former_budget", f.id, None, {**_snap(f), "via": via})
    return f


def create_former(db: Session, ctx, data) -> FormerBudget:
    return _create_former(db, ctx, data.code, data.name, data.budget_type, data.note)


def update_former(db: Session, ctx, f: FormerBudget, data) -> FormerBudget:
    if f.retired_at is not None:
        raise conflict("ALREADY_RETIRED", "This budget from before PennyWarden is retired.")
    before = _snap(f)
    fields = data.model_fields_set
    if "code" in fields and data.code is not None:
        if not _clean(data.code, 20):
            raise validation("A code is required.", "code")
        f.code = _clean(data.code, 20)
    if "name" in fields and data.name is not None:
        f.name = _clean(data.name, 120) or f.code
    if "note" in fields:
        f.note = _clean(data.note, 500)
    if "budget_type" in fields and data.budget_type is not None and data.budget_type != f.budget_type:
        by = continued_by(db, f)
        if by is not None:
            raise conflict("TYPE_LINKED", f"{budget_brief(db, by)['label']} continues it; unlink it first to change "
                                          "the type.")
        f.budget_type = data.budget_type
    if _snap(f) == before:
        return f
    f.updated_at, f.updated_by_user_id = utcnow(), ctx.user.id
    db.flush()
    audit.record(db, ctx, "FORMER_BUDGET_UPDATED", "former_budget", f.id, before,
                 {**_snap(f), "reason": _clean(getattr(data, "reason", None), 500)})
    return f


def retire_former(db: Session, ctx, f: FormerBudget, reason: str) -> FormerBudget:
    """Never deleted (BR-001): retired with a reason; the link to it is removed, its years stay (not counted)."""
    if f.retired_at is not None:
        raise conflict("ALREADY_RETIRED", "This budget from before PennyWarden is already retired.")
    by = continued_by(db, f)
    if by is not None:
        set_link(db, ctx, by, None)
    before = _snap(f)
    f.retired_at, f.retired_by_user_id, f.retire_reason = utcnow(), ctx.user.id, reason.strip()
    db.flush()
    audit.record(db, ctx, "FORMER_BUDGET_RETIRED", "former_budget", f.id, before, _snap(f))
    return f


def list_formers(db: Session, ctx, include_retired: bool = True) -> list[dict]:
    first = first_year(db, ctx.workspace_id)
    q = select(FormerBudget).where(FormerBudget.workspace_id == ctx.workspace_id)
    if not include_retired:
        q = q.where(FormerBudget.retired_at.is_(None))
    out = [former_out(db, f, first) for f in db.scalars(q)]
    out.sort(key=lambda r: (r["retired"], r["budget_type"] != "INCOME", _sort_code(r["code"]), r["name"].casefold()))
    return out


def former_detail(db: Session, ctx, f: FormerBudget) -> dict:
    first = first_year(db, ctx.workspace_id)
    rows = [{**entry_out(e, f), "counted": e.retired_at is None and f.retired_at is None and (first is None or e.year < first)}
            for e in _entries(db, [f.id], retired=True)]
    return {**former_out(db, f, first), "first_year": first, "entries": rows}


def _sort_code(code: str) -> list:
    return [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in re.split(r"[-.\s]", code or "")]


# ------------------------------------------------------------------ links
def set_link(db: Session, ctx, b: Budget, former_id: int | None, *, record: bool = True, via: str = "link") -> Budget:
    """Decisions 2 and 3: b continues the former budget (or nothing). b must be the earliest budget of its line (it
    continues no earlier PennyWarden budget); any level, same type, Other allowed, Budget 0 not; a former budget is
    continued by at most one budget. Allowed in any Fiscal Year state (reporting only)."""
    if b.is_budget_zero:
        raise AppError(422, "SYSTEM_MANAGED", "Budget 0 doesn't continue a budget from before PennyWarden.")
    if b.status == "DELETED":
        raise conflict("BUDGET_DELETED", "The budget has been deleted.")
    old = db.get(FormerBudget, b.continues_former_budget_id) if b.continues_former_budget_id else None
    if former_id is None:
        if old is None:
            return b
        b.continues_former_budget_id = None
        db.flush()
        if record:
            audit.record(db, ctx, "BUDGET_FORMER_UNLINKED", "budget", b.id, {"former": former_brief(db, old)},
                         {"former": None, "via": via})
        return b
    f = get_former(db, ctx, former_id)
    if f.retired_at is not None:
        raise conflict("FORMER_RETIRED", "That budget from before PennyWarden is retired.")
    if f.budget_type != b.budget_type:
        raise validation("A budget can only continue a budget of the same type (Income or Expense).",
                         "continues_former_budget_id")
    holder = link_holder(db, b)
    if holder.id != b.id:
        raise conflict("NOT_FIRST_OF_LINE", f"{budget_brief(db, b)['label']} continues an earlier budget; link the "
                                            f"earliest budget of its line instead ({budget_brief(db, holder)['label']}).")
    other = continued_by(db, f, except_id=b.id)
    if other is not None:
        raise conflict("ALREADY_CONTINUED", f"{former_brief(db, f)['label']} is already continued by "
                                            f"{budget_brief(db, other)['label']}.")
    if old is not None and old.id == f.id:
        return b
    b.continues_former_budget_id = f.id
    db.flush()
    if record:
        audit.record(db, ctx, "BUDGET_FORMER_LINKED", "budget", b.id, {"former": former_brief(db, old)},
                     {"former": former_brief(db, f), "via": via})
    return b


def link_options(db: Session, ctx, b: Budget) -> list[dict]:
    """Former budgets b can continue: same type, not retired, not continued by another budget."""
    taken = {r for r in db.scalars(select(Budget.continues_former_budget_id).where(
        Budget.workspace_id == ctx.workspace_id, Budget.status != "DELETED", Budget.id != b.id,
        Budget.continues_former_budget_id.is_not(None)))}
    out = []
    for f in db.scalars(select(FormerBudget).where(FormerBudget.workspace_id == ctx.workspace_id,
                                                   FormerBudget.budget_type == b.budget_type,
                                                   FormerBudget.retired_at.is_(None))):
        if f.id in taken:
            continue
        o = former_out(db, f)
        out.append({k: o[k] for k in ("id", "code", "name", "label", "years", "first_year_entered",
                                      "last_year_entered")})
    out.sort(key=lambda r: (_sort_code(r["code"]), r["name"].casefold()))
    return out


def budget_options(db: Session, ctx, f: FormerBudget, fy: FiscalYear) -> list[dict]:
    """Budgets of a Fiscal Year that can continue former budget f: the earliest budget of their line, same type, not
    Budget 0 or deleted; Other where its parent has sub-budgets. `continues` = the former budget it continues now."""
    out = []
    for b in db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id, Budget.budget_type == f.budget_type,
                                             Budget.status != "DELETED", Budget.is_budget_zero.is_(False))):
        if b.is_other:
            parent = db.get(Budget, b.parent_budget_id)
            if parent is None or not db.scalar(select(Budget.id).where(Budget.parent_budget_id == parent.id,
                                                                       Budget.is_other.is_(False),
                                                                       Budget.status != "DELETED").limit(1)):
                continue
        if link_holder(db, b).id != b.id:
            continue
        cur = db.get(FormerBudget, b.continues_former_budget_id) if b.continues_former_budget_id else None
        out.append({**budget_brief(db, b), "continues": former_brief(db, cur)})
    out.sort(key=lambda r: _sort_code(r["code"]))
    return out


# ------------------------------------------------------------------ entered years
def _check_budget(b: Budget) -> None:
    if b.is_budget_zero:
        raise AppError(422, "SYSTEM_MANAGED", "Budget 0 takes no entered history.")
    if b.status == "DELETED":
        raise AppError(409, "INVALID_STATE", "This budget is deleted.")


def _duplicate(db: Session, former_id: int, year: int, except_id: int | None = None) -> BudgetHistoryEntry | None:
    q = select(BudgetHistoryEntry).where(BudgetHistoryEntry.former_budget_id == former_id,
                                         BudgetHistoryEntry.year == year, BudgetHistoryEntry.retired_at.is_(None))
    if except_id is not None:
        q = q.where(BudgetHistoryEntry.id != except_id)
    return db.scalar(q.limit(1))


def _year_name(f: FormerBudget, code: str | None, name: str | None) -> tuple[str | None, str | None]:
    """Decision 6: the code and name of that year, kept only where they differ from the former budget's."""
    code, name = _clean(code, 20), _clean(name, 120)
    return (code if code and code != f.code else None), (name if name and name != f.name else None)


def add(db: Session, ctx, b: Budget, label: str, budgeted, actual, note: str | None, code: str | None = None,
        name: str | None = None, via: str = "single") -> BudgetHistoryEntry:
    """*Add an earlier year* on a budget's History: to the former budget its line continues, created and linked (from
    the earliest budget of the line, under its code and name) when there is none yet."""
    _check_budget(b)
    f = former_of(db, b)
    if f is None:
        holder = link_holder(db, b)
        brief = budget_brief(db, holder)
        f = _create_former(db, ctx, brief["code"], holder.name, holder.budget_type, via=via)
        set_link(db, ctx, holder, f.id, via=via)
    return add_entry(db, ctx, f, label, budgeted, actual, note, code, name, via=via, entered_on=b.id)


def add_entry(db: Session, ctx, f: FormerBudget, label: str, budgeted, actual, note: str | None,
              code: str | None = None, name: str | None = None, via: str = "single",
              entered_on: int | None = None) -> BudgetHistoryEntry:
    if f.retired_at is not None:
        raise conflict("ALREADY_RETIRED", "This budget from before PennyWarden is retired.")
    label = label.strip()
    year = _year_of(db, ctx.workspace_id, label)
    if _duplicate(db, f.id, year) is not None:
        raise AppError(409, "YEAR_ENTERED", f"{label}: figures are already entered for that year on this budget's "
                       "line; correct or retire them instead.")
    ycode, yname = _year_name(f, code, name)
    e = BudgetHistoryEntry(workspace_id=ctx.workspace_id, former_budget_id=f.id, code=ycode, name=yname,
                           fiscal_year_label=label, year=year, budgeted_cents=_cents(budgeted, "budgeted", False),
                           actual_cents=_cents(actual, "actual", True), note=_clean(note, 500),
                           created_by_user_id=ctx.user.id)
    db.add(e)
    db.flush()
    audit.record(db, ctx, "BUDGET_HISTORY_ENTERED", "former_budget", f.id, None,
                 {**entry_out(e, f), "via": via, "entered_on_budget_id": entered_on})
    return e


def _entry(db: Session, ctx, entry_id: int) -> BudgetHistoryEntry:
    e = db.get(BudgetHistoryEntry, entry_id)
    if e is None or e.workspace_id != ctx.workspace_id:
        raise not_found("Entered figure")
    return e


def former_of_entry(db: Session, e: BudgetHistoryEntry) -> FormerBudget | None:
    return db.get(FormerBudget, e.former_budget_id) if e.former_budget_id else None


def correct(db: Session, ctx, entry_id: int, body) -> BudgetHistoryEntry:
    e = _entry(db, ctx, entry_id)
    if e.retired_at is not None:
        raise AppError(409, "ALREADY_RETIRED", "This entered figure is retired; enter the year again instead.")
    f = former_of_entry(db, e)
    before = entry_out(e, f)
    fields = body.model_fields_set
    if body.fiscal_year_label is not None and body.fiscal_year_label.strip() != e.fiscal_year_label:
        label = body.fiscal_year_label.strip()
        year = _year_of(db, ctx.workspace_id, label)
        if year != e.year and f is not None and _duplicate(db, f.id, year, except_id=e.id) is not None:
            raise AppError(409, "YEAR_ENTERED", f"{label}: figures are already entered for that year on this budget's "
                           "line.")
        e.fiscal_year_label, e.year = label, year
    if body.budgeted is not None:
        e.budgeted_cents = _cents(body.budgeted, "budgeted", False)
    if body.actual is not None:
        e.actual_cents = _cents(body.actual, "actual", True)
    if body.note is not None:
        e.note = _clean(body.note, 500)
    if f is not None and ("code" in fields or "name" in fields):
        code = body.code if "code" in fields else (e.code or f.code)
        name = body.name if "name" in fields else (e.name or f.name)
        e.code, e.name = _year_name(f, code, name)
    after = entry_out(e, f)
    if after == before:
        return e
    e.updated_at, e.updated_by_user_id = utcnow(), ctx.user.id
    db.flush()
    audit.record(db, ctx, "BUDGET_HISTORY_CORRECTED", "former_budget", e.former_budget_id, before,
                 {**after, "reason": body.reason})
    return e


def retire(db: Session, ctx, entry_id: int, reason: str) -> BudgetHistoryEntry:
    e = _entry(db, ctx, entry_id)
    if e.retired_at is not None:
        raise AppError(409, "ALREADY_RETIRED", "This entered figure is already retired.")
    f = former_of_entry(db, e)
    before = entry_out(e, f)
    e.retired_at, e.retired_by_user_id, e.retire_reason = utcnow(), ctx.user.id, reason.strip()
    db.flush()
    audit.record(db, ctx, "BUDGET_HISTORY_RETIRED", "former_budget", e.former_budget_id, before, entry_out(e, f))
    return e


# ------------------------------------------------------------------ CSV import (decisions 4 and 5)
def _cell_safe(v: str) -> str:
    """CSV formula injection: a cell starting with = + - @ (or a tab/CR) is prefixed with an apostrophe."""
    v = v or ""
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def _codes(db: Session, fy: FiscalYear) -> dict[str, Budget]:
    """Display code (upper case) -> budget of the Fiscal Year that a CSV row can name: every budget and sub-budget, and
    the -00 Other of a parent with sub-budgets. Not Budget 0, not deleted."""
    out: dict[str, Budget] = {}
    rows = list(db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id, Budget.status != "DELETED",
                                                Budget.is_budget_zero.is_(False))))
    with_kids = {b.parent_budget_id for b in rows if b.parent_budget_id and not b.is_other}
    for b in rows:
        if b.is_other and b.parent_budget_id not in with_kids:
            continue
        parent = db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None
        out[budget_display_code(b, parent).upper()] = b
    return out


def template_csv(db: Session, fy: FiscalYear) -> str:
    """The columns, then one row per budget of the Fiscal Year (its code, name and type, and the former budget its line
    continues, if any) for the person to copy and fill in, one row per year."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    rows = []
    for code, b in _codes(db, fy).items():
        f = former_of(db, b)
        fcode, fname = current_label(db, f) if f is not None else ("", "")
        rows.append((code, b.name, b.budget_type.capitalize(), fcode, fname))
    rows.sort(key=lambda r: (r[2] != "Income", _sort_code(r[0])))
    for code, name, t, fcode, fname in rows:
        w.writerow([_cell_safe(code), _cell_safe(name), t, _cell_safe(fcode), _cell_safe(fname), "", "", "", "", ""])
    return buf.getvalue()


def _norm_head(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower().lstrip("﻿"))


def _row_type(v: str) -> str | None:
    """None: blank; "?": not Income/Expense."""
    if not v:
        return None
    return _TYPES.get(v.strip().lower(), "?")


def preview(db: Session, ctx, fy: FiscalYear, text: str) -> dict:
    """Reads the CSV and says, row by row, what would happen - MATCHED, REFUSED (with the reason) or DUPLICATE (the year
    is already entered on that line, or listed twice) - and, line by line, which former budget the rows go to (new or
    existing) and which budget will continue it. Saves nothing."""
    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise validation(f"The file is too large (at most {MAX_CSV_BYTES // 1024} KB).", "csv")
    reader = csv.reader(io.StringIO(text))
    try:
        head = next(reader)
    except StopIteration:
        raise validation("The file is empty.", "csv") from None
    names = [_norm_head(h) for h in head]
    missing = [c for c in REQUIRED_COLUMNS if c not in names]
    if "budget code" not in names and "former code" not in names:
        missing.append("budget code or former code")
    if missing:
        raise validation("The first row must name the columns: budget code, type, former code, former name, year, "
                         "budgeted, actual, note, line (missing: " + ", ".join(missing) + "). Download the template "
                         "to start from.", "csv")
    col = {c: names.index(c) for c in CSV_COLUMNS if c in names}
    codes = _codes(db, fy)
    first = first_year(db, ctx.workspace_id)
    rows: list[dict] = []
    for n, raw in enumerate(reader, start=2):
        def cell(c, raw=raw, size=200):
            i = col.get(c)
            return (raw[i] if i is not None and i < len(raw) else "").strip()[:size]

        v = {c: cell(c) for c in CSV_COLUMNS}
        # a blank row, or a template row left as it is (only the budget's code, name and type)
        if not any(v[c] for c in ("year", "budgeted", "actual", "former code", "former name", "note", "line")):
            continue
        if len(rows) >= MAX_CSV_ROWS:
            raise validation(f"Too many rows (at most {MAX_CSV_ROWS}).", "csv")
        r = {"line": n, "year_label": v["year"][:40], "code": v["budget code"][:20], "former_code": v["former code"][:20],
             "former_name": v["former name"][:120], "type": None, "budgeted": v["budgeted"], "actual": v["actual"],
             "note": cell("note", size=500) or None, "line_key": v["line"][:60], "status": "MATCHED", "reason": None,
             "budget_id": None, "budget_name": None, "year": None, "group": None}
        b = codes.get(r["code"].upper()) if r["code"] else None
        t = _row_type(v["type"])
        year = label_year(r["year_label"])
        reason = None
        if not r["year_label"]:
            reason = "No year."
        elif year is None:
            reason = "The year must include the year, for example FY2021."
        elif first is not None and year >= first:
            reason = f"Only years before the first Fiscal Year in PennyWarden (FY{first})."
        elif r["code"] and b is None:
            reason = f"No budget {r['code']} in {fy.display_name}."
        elif not r["code"] and not r["former_code"]:
            reason = "A budget code or a former code is needed."
        elif t == "?":
            reason = "Type must be Income or Expense."
        elif b is not None and t is not None and t != b.budget_type:
            reason = f"Type {t.capitalize()} doesn't match budget {r['code']} ({b.budget_type.capitalize()})."
        elif b is None and t is None:
            reason = "Type (Income or Expense) is needed when no budget code is given."
        else:
            try:
                bc = _cents(r["budgeted"], "budgeted", False)
                ac = _cents(r["actual"], "actual", True)
                r.update(budgeted=fmt(bc), actual=fmt(ac))
            except AppError as e:
                reason = f"{e.extra.get('errors', [{}])[0].get('field', 'amount').capitalize()}: {e.message}"
        if reason:
            r.update(status="REFUSED", reason=reason)
            rows.append(r)
            continue
        r.update(budget_id=b.id if b is not None else None, budget_name=b.name if b is not None else None,
                 type=t or b.budget_type, year=year)
        r["group"] = (f"line {r['line_key']}" if r["line_key"] else f"budget {r['code'].upper()}" if b is not None
                      else f"former {r['former_code'].upper()}")
        rows.append(r)

    groups: dict[str, list[dict]] = {}
    for r in rows:
        if r["status"] == "MATCHED":
            # by former code: an Income and an Expense row with the same code are two lines
            key = r["group"].casefold() + (f" {r['type']}" if r["group"].startswith("former ") else "")
            groups.setdefault(key, []).append(r)
    lines, new_names, linked_formers, holders = [], {}, {}, {}
    for key, grows in groups.items():
        g = _plan_group(db, ctx, fy, grows, codes)
        if g["refused"] is None and g["former_id"] is None:
            ident = (g["budget_type"], g["former_code"].casefold(), g["former_name"].casefold())
            if ident in new_names:
                g["refused"] = f"Another line of this file ({new_names[ident]}) is also {g['former_code']} " \
                               f"{g['former_name']}; give the rows the same line, or different names."
            else:
                new_names[ident] = grows[0]["group"]
        if g["refused"] is None and g["former_id"] is not None and g["link_action"] == "NEW":
            if g["former_id"] in linked_formers:
                g["refused"] = f"{g['former_code']} {g['former_name']} is continued by another line of this file " \
                               f"({linked_formers[g['former_id']]})."
            else:
                linked_formers[g["former_id"]] = grows[0]["group"]
        if g["refused"] is None and g["holder_id"] is not None:
            if g["holder_id"] in holders:
                g["refused"] = f"{g['link']['label']} is linked by another line of this file ({holders[g['holder_id']]})."
            else:
                holders[g["holder_id"]] = grows[0]["group"]
        if g["refused"] is not None:
            for r in grows:
                r.update(status="REFUSED", reason=g["refused"])
        else:
            have = ({e.year for e in _entries(db, [g["former_id"]])} if g["former_id"] is not None else set())
            seen: dict[int, int] = {}
            for r in sorted(grows, key=lambda x: x["line"]):
                if r["year"] in seen:
                    r.update(status="DUPLICATE", reason=f"Listed twice in the file (line {seen[r['year']]}).")
                elif r["year"] in have:
                    r.update(status="DUPLICATE", reason="Already entered for that year on this line.")
                else:
                    seen[r["year"]] = r["line"]
        g["years"] = sum(1 for r in grows if r["status"] == "MATCHED")
        g["rows"] = [r["line"] for r in grows]
        lines.append(g)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("MATCHED", "REFUSED", "DUPLICATE")}
    return {"fiscal_year_id": fy.id, "rows": rows, "lines": lines, "counts": counts,
            "new_former_budgets": sum(1 for g in lines if g["years"] and g["action"] == "NEW"),
            "new_links": sum(1 for g in lines if g["years"] and g["link_action"] == "NEW")}


def _plan_group(db: Session, ctx, fy: FiscalYear, grows: list[dict], codes: dict[str, Budget]) -> dict:
    """One line of the file: which former budget its rows go to and which budget will continue it."""
    g = {"key": grows[0]["group"], "refused": None, "former_id": None, "former_code": "", "former_name": "",
         "budget_type": None, "action": None, "link": None, "link_action": None, "holder_id": None}
    bids = {r["budget_id"] for r in grows if r["budget_id"] is not None}
    types = {r["type"] for r in grows}
    if len(bids) > 1:
        g["refused"] = f"The {g['key']} names more than one budget code."
        return g
    if len(types) > 1:
        g["refused"] = f"The rows of the {g['key']} have different types."
        return g
    t = types.pop()
    g["budget_type"] = t
    target = db.get(Budget, bids.pop()) if bids else None
    latest = max(grows, key=lambda r: (r["year"], r["line"]))
    tbrief = budget_brief(db, target) if target is not None else None
    fcode = latest["former_code"] or next((r["former_code"] for r in reversed(grows) if r["former_code"]), "") \
        or (tbrief["code"] if tbrief else "")
    fname = latest["former_name"] or next((r["former_name"] for r in reversed(grows) if r["former_name"]), "") \
        or (target.name if target is not None else fcode)
    g["former_code"], g["former_name"] = fcode, fname
    f = former_of(db, target) if target is not None else None
    if f is None:
        cands = []
        for c in db.scalars(select(FormerBudget).where(FormerBudget.workspace_id == ctx.workspace_id,
                                                       FormerBudget.retired_at.is_(None))):
            cur = current_label(db, c)
            if any(code.casefold() == fcode.casefold() and name.casefold() == fname.casefold()
                   for code, name in (cur, (c.code, c.name))):
                cands.append(c)
        if len(cands) > 1:
            g["refused"] = (f"Several budgets from before PennyWarden are called {fcode} {fname}; add these years on "
                            "Budgets → Before PennyWarden instead.")
            return g
        if cands:
            f = cands[0]
            if target is not None:
                other = continued_by(db, f)
                holder = link_holder(db, target)
                if other is not None and other.id != holder.id:
                    g["refused"] = f"{fcode} {fname} is already continued by {budget_brief(db, other)['label']}."
                    return g
    if f is not None and f.budget_type != t:
        g["refused"] = f"{fcode} {fname} is {f.budget_type.capitalize()}, not {t.capitalize()}."
        return g
    if f is not None:
        g["former_id"], g["action"] = f.id, "EXISTING"
        g["former_code"], g["former_name"] = current_label(db, f)
    else:
        g["action"] = "NEW"
    if target is not None:
        holder = link_holder(db, target)
        g["holder_id"], g["link"] = holder.id, budget_brief(db, holder)
        g["link_action"] = "EXISTING" if f is not None and holder.continues_former_budget_id == f.id else "NEW"
        if g["link_action"] == "NEW" and holder.continues_former_budget_id:
            cur = db.get(FormerBudget, holder.continues_former_budget_id)
            if cur is not None and cur.retired_at is None:
                g["refused"] = f"{g['link']['label']} already continues {former_brief(db, cur)['label']}."
    return g


def import_csv(db: Session, ctx, fy: FiscalYear, text: str) -> dict:
    """Saves the MATCHED rows of the preview (all of them, or nothing if one fails): creates the new former budgets,
    makes the new links and enters the years; refused and duplicate rows are left out."""
    p = preview(db, ctx, fy, text)
    saved = created = linked = 0
    by_line = {r["line"]: r for r in p["rows"]}
    for g in p["lines"]:
        rows = [by_line[n] for n in g["rows"] if by_line[n]["status"] == "MATCHED"]
        if not rows:
            continue
        if g["former_id"] is not None:
            f = get_former(db, ctx, g["former_id"])
        else:
            f = _create_former(db, ctx, g["former_code"], g["former_name"], g["budget_type"], via="csv")
            created += 1
        if g["holder_id"] is not None and g["link_action"] == "NEW":
            set_link(db, ctx, db.get(Budget, g["holder_id"]), f.id, via="csv")
            linked += 1
        for r in rows:
            add_entry(db, ctx, f, r["year_label"], r["budgeted"], r["actual"], r["note"],
                      r["former_code"] or None, r["former_name"] or None, via="csv")
            saved += 1
    if not saved:
        raise validation("Nothing to import: no row matched.", "csv")
    audit.record(db, ctx, "BUDGET_HISTORY_IMPORTED", "fiscal_year", fy.id, None,
                 {"saved": saved, "refused": p["counts"]["REFUSED"], "duplicates": p["counts"]["DUPLICATE"],
                  "former_budgets_created": created, "links_made": linked})
    return {**p, "saved": saved, "former_budgets_created": created, "links_made": linked}
