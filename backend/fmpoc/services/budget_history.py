"""2.2.0 (#284): budget history before PennyWarden.

A Budget Manager enters a budget line's **budgeted and actual figures for years before the first Fiscal Year in
PennyWarden** (from the old spreadsheets), so the budget's History, the Budget Review and the Planning Sheet's appended
review show the full history. Decisions (Kyle, 2026-10-24):

* **Any budget level.** A parent with its own entered figure shows it; without one it shows the sum of its
  sub-budgets' entered figures (still *Entered*). Both entered and different: the parent's own figure with a mismatch
  note. Nothing blocks the save. Budget 0 and the system-managed Other budgets take no history (like the #89 links).
* **Stored against the oldest budget of the line** (the #89 continuation links) and read for every budget of the
  line, so it follows the line through renumbering, and a link added later to an even older budget keeps it.
* **Years in PennyWarden stay refused**: only a year before the first Fiscal Year in PennyWarden (by the year in its
  name, else its end date). If a Fiscal Year is added later that covers an entered year, the entry is kept but no
  longer counted (the History view says so) - nothing is counted twice.
* **Reporting only**: never part of actuals, registers or Fiscal Year closure (BR-048).
* **Never deleted** (BR-001): corrected (reason required) or retired (reason required); every change audited with
  before and after values.
* **CSV import** (second half): year, budget code, budgeted, actual, note - matched on the codes of the chosen
  Fiscal Year, previewed (matched / refused with the reason / duplicate) before anything is saved.
"""
from __future__ import annotations

import csv
import io
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, not_found, validation
from ..models import Budget, BudgetHistoryEntry, FiscalYear, utcnow
from ..money import fmt, parse_amount
from .common import budget_display_code
from .fundraiser_series import fy_year, label_year

MAX_CSV_ROWS = 2000
MAX_CSV_BYTES = 512 * 1024
CSV_COLUMNS = ["year", "budget code", "budgeted", "actual", "note"]


# ------------------------------------------------------------------ years and lines
def first_year(db: Session, ws_id: int) -> int | None:
    """The year of the first Fiscal Year in PennyWarden (None: no Fiscal Year yet)."""
    years = [fy_year(f) for f in db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id))]
    return min(years) if years else None


def line_ids(db: Session, b: Budget) -> list[int]:
    """The budget and every earlier budget it continues (#89), newest first; the last one is the line's oldest."""
    out, seen, cur = [b.id], {b.id}, b
    while cur.continues_budget_id and cur.continues_budget_id not in seen:
        cur = db.get(Budget, cur.continues_budget_id)
        if cur is None:
            break
        out.append(cur.id)
        seen.add(cur.id)
    return out


def _sub_line_ids(db: Session, parent: Budget) -> list[list[int]]:
    """The lines of the sub-budgets of a parent's line (the parent and the parents it continues), one list per
    sub-budget line, without duplicates."""
    lines: list[list[int]] = []
    covered: set[int] = set()
    for pid in line_ids(db, parent):
        for k in db.scalars(select(Budget).where(Budget.parent_budget_id == pid, Budget.system_managed.is_(False),
                                                 Budget.status != "DELETED")):
            if k.id in covered:
                continue
            ids = line_ids(db, k)
            covered.update(ids)
            lines.append(ids)
    return lines


def _active(db: Session, ids: list[int]) -> list[BudgetHistoryEntry]:
    if not ids:
        return []
    return list(db.scalars(select(BudgetHistoryEntry).where(BudgetHistoryEntry.budget_id.in_(ids),
                                                            BudgetHistoryEntry.retired_at.is_(None))
                           .order_by(BudgetHistoryEntry.year, BudgetHistoryEntry.id)))


def entry_out(e: BudgetHistoryEntry) -> dict:
    return {"id": e.id, "budget_id": e.budget_id, "fiscal_year_label": e.fiscal_year_label, "year": e.year,
            "budgeted": fmt(e.budgeted_cents), "actual": fmt(e.actual_cents), "note": e.note,
            "retired": e.retired_at is not None,
            "retired_at": e.retired_at.isoformat(timespec="seconds") + "Z" if e.retired_at else None,
            "retire_reason": e.retire_reason}


# ------------------------------------------------------------------ figures for reports
def figures(db: Session, b: Budget, first: int | None) -> dict[int, dict]:
    """year -> the entered figure shown for budget `b` (only years before the first Fiscal Year in PennyWarden):
    {label, budgeted (cents), actual (cents), source: own|subs, mismatch: None|{budgeted, actual} (sum of subs)}."""
    if b.system_managed:
        return {}
    own = {e.year: e for e in _active(db, line_ids(db, b))}
    subs: dict[int, dict] = {}
    if b.parent_budget_id is None:
        for ids in _sub_line_ids(db, b):
            for e in _active(db, ids):
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
                      "source": "own", "entry_id": e.id, "note": e.note, "mismatch": mismatch}
        else:
            s = subs[y]
            out[y] = {"label": s["labels"][0], "budgeted": s["budgeted"], "actual": s["actual"], "source": "subs",
                      "entry_id": None, "note": None, "mismatch": None}
    return out


def year_labels(db: Session, ws_id: int, first: int | None) -> dict[int, str]:
    """year -> column heading for every entered year before the first Fiscal Year (the label most often used)."""
    counts: dict[int, dict[str, int]] = {}
    for e in db.scalars(select(BudgetHistoryEntry).where(BudgetHistoryEntry.workspace_id == ws_id,
                                                         BudgetHistoryEntry.retired_at.is_(None))):
        if first is not None and e.year >= first:
            continue
        c = counts.setdefault(e.year, {})
        c[e.fiscal_year_label] = c.get(e.fiscal_year_label, 0) + 1
    return {y: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for y, c in counts.items()}


def has_entries(db: Session, b: Budget) -> bool:
    if b.system_managed:
        return False
    ids = line_ids(db, b)
    if b.parent_budget_id is None:
        ids += [i for line in _sub_line_ids(db, b) for i in line]
    return bool(_active(db, ids))


# ------------------------------------------------------------------ the History view
def view(db: Session, ctx, b: Budget) -> dict:
    """The entered years of a budget's line for its History view: its own entries (retired ones too, marked), and for a
    parent the years filled only by its sub-budgets' entries."""
    first = first_year(db, ctx.workspace_id)
    ids = line_ids(db, b)
    own = list(db.scalars(select(BudgetHistoryEntry).where(BudgetHistoryEntry.budget_id.in_(ids))
                          .order_by(BudgetHistoryEntry.year, BudgetHistoryEntry.id))) if not b.system_managed else []
    shown = figures(db, b, first)
    rows = []
    for e in own:
        f = shown.get(e.year) if e.retired_at is None else None
        rows.append({**entry_out(e), "source": "ENTERED", "from_sub_budgets": False,
                     "counted": e.retired_at is None and (first is None or e.year < first),
                     "mismatch": f["mismatch"] if f and f.get("entry_id") == e.id else None})
    for y, f in sorted(shown.items()):
        if f["source"] == "subs":
            rows.append({"id": None, "budget_id": None, "fiscal_year_label": f["label"], "year": y,
                         "budgeted": fmt(f["budgeted"]), "actual": fmt(f["actual"]), "note": None, "retired": False,
                         "retired_at": None, "retire_reason": None, "source": "ENTERED", "from_sub_budgets": True,
                         "counted": True, "mismatch": None})
    rows.sort(key=lambda r: (r["year"], r["from_sub_budgets"], r["id"] or 0))
    return {"first_year": first, "can_enter": not b.system_managed, "entries": rows}


# ------------------------------------------------------------------ changes
def _cents(v, field: str, allow_negative: bool) -> int:
    if v is None or str(v).strip() == "":
        raise validation("This amount is required.", field)
    try:
        return parse_amount(str(v).strip().replace("$", "").replace(",", ""), allow_negative=allow_negative,
                            allow_zero=True)
    except ValueError as e:
        raise validation(str(e).capitalize() + ".", field) from None


def _year_of(db: Session, ws_id: int, label: str) -> int:
    year = label_year(label)
    if year is None:
        raise validation("Include the year in the Fiscal Year label, for example FY2021.", "fiscal_year_label")
    first = first_year(db, ws_id)
    if first is not None and year >= first:
        raise AppError(409, "YEAR_IN_PENNYWARDEN", f"{label}: only years before the first Fiscal Year in PennyWarden "
                       f"(FY{first}) can be entered; that year's figures come from PennyWarden.")
    return year


def _check_budget(b: Budget) -> None:
    if b.system_managed:
        raise AppError(422, "SYSTEM_MANAGED", "Budget 0 and the system-managed Other budgets take no entered history.")
    if b.status == "DELETED":
        raise AppError(409, "INVALID_STATE", "This budget is deleted.")


def _duplicate(db: Session, ids: list[int], year: int, except_id: int | None = None) -> BudgetHistoryEntry | None:
    q = select(BudgetHistoryEntry).where(BudgetHistoryEntry.budget_id.in_(ids), BudgetHistoryEntry.year == year,
                                         BudgetHistoryEntry.retired_at.is_(None))
    if except_id is not None:
        q = q.where(BudgetHistoryEntry.id != except_id)
    return db.scalar(q.limit(1))


def add(db: Session, ctx, b: Budget, label: str, budgeted, actual, note: str | None,
        via: str = "single") -> BudgetHistoryEntry:
    _check_budget(b)
    label = label.strip()
    year = _year_of(db, ctx.workspace_id, label)
    ids = line_ids(db, b)
    if _duplicate(db, ids, year) is not None:
        raise AppError(409, "YEAR_ENTERED", f"{label}: figures are already entered for that year on this budget's "
                       "line; correct or retire them instead.")
    e = BudgetHistoryEntry(workspace_id=ctx.workspace_id, budget_id=ids[-1], fiscal_year_label=label, year=year,
                           budgeted_cents=_cents(budgeted, "budgeted", False),
                           actual_cents=_cents(actual, "actual", True),
                           note=(note or "").strip() or None, created_by_user_id=ctx.user.id)
    db.add(e)
    db.flush()
    audit.record(db, ctx, "BUDGET_HISTORY_ENTERED", "budget", e.budget_id, None,
                 {**entry_out(e), "via": via, "entered_on_budget_id": b.id})
    return e


def _entry(db: Session, ctx, entry_id: int) -> BudgetHistoryEntry:
    e = db.get(BudgetHistoryEntry, entry_id)
    if e is None or e.workspace_id != ctx.workspace_id:
        raise not_found("Entered figure")
    return e


def correct(db: Session, ctx, entry_id: int, body) -> BudgetHistoryEntry:
    e = _entry(db, ctx, entry_id)
    if e.retired_at is not None:
        raise AppError(409, "ALREADY_RETIRED", "This entered figure is retired; enter the year again instead.")
    before = entry_out(e)
    if body.fiscal_year_label is not None and body.fiscal_year_label.strip() != e.fiscal_year_label:
        label = body.fiscal_year_label.strip()
        year = _year_of(db, ctx.workspace_id, label)
        b = db.get(Budget, e.budget_id)
        if year != e.year and _duplicate(db, line_ids(db, b), year, except_id=e.id) is not None:
            raise AppError(409, "YEAR_ENTERED", f"{label}: figures are already entered for that year on this budget's "
                           "line.")
        e.fiscal_year_label, e.year = label, year
    if body.budgeted is not None:
        e.budgeted_cents = _cents(body.budgeted, "budgeted", False)
    if body.actual is not None:
        e.actual_cents = _cents(body.actual, "actual", True)
    if body.note is not None:
        e.note = body.note.strip() or None
    after = entry_out(e)
    if after == before:
        return e
    e.updated_at, e.updated_by_user_id = utcnow(), ctx.user.id
    db.flush()
    audit.record(db, ctx, "BUDGET_HISTORY_CORRECTED", "budget", e.budget_id, before, {**after, "reason": body.reason})
    return e


def retire(db: Session, ctx, entry_id: int, reason: str) -> BudgetHistoryEntry:
    e = _entry(db, ctx, entry_id)
    if e.retired_at is not None:
        raise AppError(409, "ALREADY_RETIRED", "This entered figure is already retired.")
    before = entry_out(e)
    e.retired_at, e.retired_by_user_id, e.retire_reason = utcnow(), ctx.user.id, reason.strip()
    db.flush()
    audit.record(db, ctx, "BUDGET_HISTORY_RETIRED", "budget", e.budget_id, before, entry_out(e))
    return e


# ------------------------------------------------------------------ CSV import (decision 2)
def _codes(db: Session, fy: FiscalYear) -> dict[str, Budget]:
    out = {}
    for b in db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id, Budget.status != "DELETED",
                                             Budget.system_managed.is_(False))):
        parent = db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None
        out[budget_display_code(b, parent).upper()] = b
    return out


def template_csv(db: Session, fy: FiscalYear) -> str:
    """The columns, then one row per budget of the Fiscal Year with its code (and its name, which the import ignores)
    for the person to copy and fill in, one row per year."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS + ["budget name (ignored)"])
    rows = []
    for code, b in _codes(db, fy).items():
        rows.append((code, b.name))
    rows.sort(key=lambda r: [int(x) if x.isdigit() else x for x in re.split(r"-", r[0])])
    for code, name in rows:
        w.writerow(["", code, "", "", "", name])
    return buf.getvalue()


def _norm_head(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower().lstrip("﻿"))


def preview(db: Session, ctx, fy: FiscalYear, text: str) -> dict:
    """Reads the CSV and says, row by row, what would happen: MATCHED, REFUSED (with the reason) or DUPLICATE (the year
    is already entered on that line, or listed twice in the file). Saves nothing."""
    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise validation(f"The file is too large (at most {MAX_CSV_BYTES // 1024} KB).", "csv")
    reader = csv.reader(io.StringIO(text))
    try:
        head = next(reader)
    except StopIteration:
        raise validation("The file is empty.", "csv") from None
    names = [_norm_head(h) for h in head]
    missing = [c for c in CSV_COLUMNS[:4] if c not in names]
    if missing:
        raise validation("The first row must name the columns: year, budget code, budgeted, actual, note (missing: "
                         + ", ".join(missing) + "). Download the template to start from.", "csv")
    col = {c: names.index(c) for c in CSV_COLUMNS if c in names}
    codes = _codes(db, fy)
    first = first_year(db, ctx.workspace_id)
    rows, seen = [], {}
    for n, raw in enumerate(reader, start=2):
        if not any((x or "").strip() for x in raw):
            continue
        if len(rows) >= MAX_CSV_ROWS:
            raise validation(f"Too many rows (at most {MAX_CSV_ROWS}).", "csv")

        def cell(c, raw=raw):
            i = col.get(c)
            return (raw[i] if i is not None and i < len(raw) else "").strip()

        r = {"line": n, "year_label": cell("year")[:40], "code": cell("budget code")[:20], "budgeted": cell("budgeted"),
             "actual": cell("actual"), "note": cell("note")[:500] or None, "status": "MATCHED", "reason": None,
             "budget_id": None, "budget_name": None, "year": None}
        b = codes.get(r["code"].upper())
        year = label_year(r["year_label"])
        reason = None
        if not r["year_label"]:
            reason = "No year."
        elif year is None:
            reason = "The year must include the year, for example FY2021."
        elif first is not None and year >= first:
            reason = f"Only years before the first Fiscal Year in PennyWarden (FY{first})."
        elif b is None:
            reason = f"No budget {r['code'] or '(blank)'} in {fy.display_name}."
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
        ids = line_ids(db, b)
        r.update(budget_id=b.id, budget_name=b.name, year=year)
        key = (ids[-1], year)
        if key in seen:
            r.update(status="DUPLICATE", reason=f"Listed twice in the file (line {seen[key]}).")
        elif _duplicate(db, ids, year) is not None:
            r.update(status="DUPLICATE", reason="Already entered for that year on this budget's line.")
        else:
            seen[key] = n
        rows.append(r)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("MATCHED", "REFUSED", "DUPLICATE")}
    return {"fiscal_year_id": fy.id, "rows": rows, "counts": counts}


def import_csv(db: Session, ctx, fy: FiscalYear, text: str) -> dict:
    """Saves the MATCHED rows of the preview (all of them, or nothing if one fails); refused and duplicate rows are
    left out."""
    p = preview(db, ctx, fy, text)
    saved = 0
    for r in p["rows"]:
        if r["status"] != "MATCHED":
            continue
        add(db, ctx, db.get(Budget, r["budget_id"]), r["year_label"], r["budgeted"], r["actual"], r["note"], via="csv")
        saved += 1
    if not saved:
        raise validation("Nothing to import: no row matched.", "csv")
    audit.record(db, ctx, "BUDGET_HISTORY_IMPORTED", "fiscal_year", fy.id, None,
                 {"saved": saved, "refused": p["counts"]["REFUSED"], "duplicates": p["counts"]["DUPLICATE"]})
    return {**p, "saved": saved}
