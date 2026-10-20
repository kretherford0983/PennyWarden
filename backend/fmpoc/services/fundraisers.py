"""v1.6.0 CR-033: optional Fundraiser module (plan: project doc claude/freedger-plan-1.6.md).

A fundraiser groups the activity of up to one income and one expense budget per Fiscal Year (at most two adjacent
Fiscal Years). Rules agreed with the product owner (2026-10-01):

- Event start/end dates are the physical dates of the event and are display only. Inclusion is by budget: every
  ACTIVE, live allocation to a selected budget (a parent includes all its children) that matches the optional
  description filter, whatever its transaction date.
- A fundraiser can be created as a "shell" (no budgets) as soon as it is agreed - before its Fiscal Year exists.
  Creating it (or moving its event dates) is refused only when the Fiscal Year covering the event start exists and
  is Closed.
- Budgets of a Fiscal Year may be chosen when that Fiscal Year exists, is not Closed and the event dates fall inside
  it or within 3 months of its start or end. Budgets of a Closed Fiscal Year are frozen.
- Filter: plain text = case-insensitive "contains"; with `filter_regex` a regular expression evaluated by RE2
  (linear time, so a pattern can never hang the server; no backreferences or look-arounds).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

import re2
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, not_found, validation
from ..models import (Attachment, BankAccount, Budget, FiscalYear, Fundraiser, FundraiserBucket, FundraiserBucketCategory,
                      FundraiserBucketLine,
                      FundraiserBudget, FundraiserClassification, FundraiserExclusion, RegisterTransaction,
                      TransactionAllocation, Workspace, utcnow)
from ..money import fmt, parse_amount
from . import bank_accounts as bank
from .attachments import DISPLAY_ORDER
from .common import add_months, budget_label, covering_fiscal_years, fy_brief, get_scoped

WINDOW_MONTHS = 3
MAX_FISCAL_YEARS = 2
FILTER_MAX = 200
KINDS = ("INCOME", "EXPENSE")
# v1.6.1 CR-034: part of a line that is not fundraiser money. Float out = cash taken from the bank for the cash box
# (expense side); float returned = that cash coming back inside a deposit (income side).
CLASSIFICATIONS = {"CASH_FLOAT_OUT": ("EXPENSE", "Cash float out"), "CASH_FLOAT_RETURNED": ("INCOME", "Cash float returned")}
MAX_BUCKETS = 30
MAX_CATEGORIES = 30


# ------------------------------------------------------------------ module switch
def module_enabled(db: Session, ws_id: int | None) -> bool:
    ws = db.get(Workspace, ws_id) if ws_id else None
    return bool(ws and ws.fundraisers_enabled)


def require_module(db: Session, ctx) -> None:
    if not module_enabled(db, ctx.workspace_id):
        raise AppError(404, "MODULE_DISABLED", "The Fundraiser module is not turned on.")


def set_module(db: Session, ctx, enabled: bool) -> bool:
    ws = db.get(Workspace, ctx.workspace_id)
    before = bool(ws.fundraisers_enabled)
    if before != enabled:
        ws.fundraisers_enabled = enabled
        audit.record(db, ctx, "MODULE_ENABLED" if enabled else "MODULE_DISABLED", "module", "fundraisers",
                     {"fundraisers_enabled": before}, {"fundraisers_enabled": enabled}, category="SECURITY")
    return enabled


# ------------------------------------------------------------------ filter
def compile_filter(text: str | None, is_regex: bool):
    """Returns a predicate over a description, or None when there is no filter. Raises 422 for a bad pattern."""
    text = (text or "").strip()
    if not text:
        return None
    if len(text) > FILTER_MAX:
        raise validation(f"The filter can be at most {FILTER_MAX} characters.", "filter_text")
    opts = re2.Options()
    opts.case_sensitive = False
    opts.log_errors = False
    if not is_regex:
        opts.literal = True
    try:
        pat = re2.compile(text, opts)
    except Exception:  # re2.error - message is engine-specific; keep it simple for users
        raise validation("The regular expression is not valid (backreferences and look-arounds are not supported).",
                         "filter_text") from None
    return lambda s: bool(s) and pat.search(s) is not None


# ------------------------------------------------------------------ Fiscal Year window rule
def in_window(fy: FiscalYear, start: dt.date, end: dt.date) -> bool:
    """The event lies inside the Fiscal Year or within 3 months of its start or end."""
    return start <= add_months(fy.end_date, WINDOW_MONTHS) and end >= add_months(fy.start_date, -WINDOW_MONTHS)


def _all_fys(db: Session, ws_id: int) -> list[FiscalYear]:
    return list(db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id).order_by(FiscalYear.start_date)))


def eligible_fiscal_years(db: Session, ws_id: int, start: dt.date, end: dt.date) -> list[FiscalYear]:
    return [fy for fy in _all_fys(db, ws_id) if fy.status != "CLOSED" and in_window(fy, start, end)]


def _adjacent(db: Session, ws_id: int, a: FiscalYear, b: FiscalYear) -> bool:
    fys = _all_fys(db, ws_id)
    ia, ib = fys.index(a), fys.index(b)
    return abs(ia - ib) == 1


def check_event_dates(db: Session, ws_id: int, start: dt.date, end: dt.date) -> None:
    if end < start:
        raise validation("The event end date cannot be before its start date.", "end_date")
    closed = [fy for fy in covering_fiscal_years(db, ws_id, start) if fy.status == "CLOSED"]
    if closed:
        raise AppError(409, "FISCAL_YEAR_CLOSED",
                       f"The event date falls in {closed[0].display_name}, which is closed. Fundraisers can only be "
                       "set up while the Fiscal Year of the event is open.")


# ------------------------------------------------------------------ budgets
def leaf_ids(db: Session, b: Budget) -> list[int]:
    """A parent includes itself and all its children; a child is only itself."""
    if b.parent_budget_id is not None:
        return [b.id]
    kids = db.scalars(select(Budget.id).where(Budget.parent_budget_id == b.id))
    return [b.id, *kids]


def _parent(db: Session, b: Budget) -> Budget | None:
    return db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None


def _has_explicit_children(db: Session, parent_id: int) -> bool:
    return db.scalar(select(Budget.id).where(Budget.parent_budget_id == parent_id, Budget.is_other.is_(False)).limit(1)) is not None


def budget_warnings(db: Session, b: Budget) -> list[dict]:
    out = []
    if b.is_other:
        p = _parent(db, b)
        if p is not None and _has_explicit_children(db, p.id):
            out.append({"code": "OTHER_BUDGET", "message": "An “Other” budget collects everything not planned in a "
                        "sub-budget. Items allocated to it that are not part of this fundraiser will affect the "
                        "validity of the fundraiser figures."})
    elif b.parent_budget_id is None and _has_explicit_children(db, b.id):
        out.append({"code": "PARENT_BUDGET", "message": "A parent budget includes all of its sub-budgets. Everything "
                    "allocated to any of them counts towards this fundraiser."})
    return out


def budget_brief(db: Session, b: Budget) -> dict:
    p = _parent(db, b)
    label = budget_label(p, None) if (b.is_other and p is not None and not _has_explicit_children(db, p.id)) else budget_label(b, p)
    return {"id": b.id, "label": label, "budget_type": b.budget_type, "fiscal_year_id": b.fiscal_year_id,
            "status": b.status, "warnings": budget_warnings(db, b)}


def budget_options(db: Session, ctx, start: dt.date, end: dt.date) -> list[dict]:
    """Per eligible Fiscal Year: the income and expense budgets that can be chosen (parents and sub-budgets)."""
    if end < start:
        return []
    out = []
    for fy in eligible_fiscal_years(db, ctx.workspace_id, start, end):
        budgets = list(db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id, Budget.status != "DELETED")
                                  .order_by(Budget.parent_code, Budget.child_code)))
        opts: dict[str, list] = {"INCOME": [], "EXPENSE": []}
        for p in (b for b in budgets if b.parent_budget_id is None and not b.is_budget_zero):
            kids = [k for k in budgets if k.parent_budget_id == p.id]
            explicit = [k for k in kids if not k.is_other]
            opts[p.budget_type].append({"id": p.id, "label": budget_label(p, None), "status": p.status,
                                        "level": 0, "warnings": budget_warnings(db, p)})
            if explicit:
                for k in [*explicit, *[k for k in kids if k.is_other]]:
                    opts[p.budget_type].append({"id": k.id, "label": budget_label(k, p), "status": k.status,
                                                "level": 1, "warnings": budget_warnings(db, k)})
        out.append({"fiscal_year": fy_brief(fy), "income": opts["INCOME"], "expense": opts["EXPENSE"]})
    return out


def _validate_budgets(db: Session, ctx, f: Fundraiser | None, start: dt.date, end: dt.date,
                      budget_ids: list[int]) -> list[tuple[Budget, FiscalYear]]:
    chosen: list[tuple[Budget, FiscalYear]] = []
    seen: set[tuple[int, str]] = set()
    existing = {fb.budget_id for fb in (f.budgets if f else [])}
    for bid in dict.fromkeys(budget_ids):
        b = db.get(Budget, bid)
        fy = db.get(FiscalYear, b.fiscal_year_id) if b else None
        if b is None or fy is None or fy.workspace_id != ctx.workspace_id:
            raise not_found("Budget")
        if b.is_budget_zero:
            raise validation("Budget 0 cannot be used for a fundraiser.", "budget_ids")
        key = (fy.id, b.budget_type)
        if key in seen:
            kind = "income" if b.budget_type == "INCOME" else "expense"
            raise validation(f"Only one {kind} budget can be chosen for {fy.display_name}.", "budget_ids")
        seen.add(key)
        if fy.status == "CLOSED":
            if bid not in existing:
                raise AppError(409, "FISCAL_YEAR_CLOSED", f"{fy.display_name} is closed; its budgets cannot be added.")
        elif not in_window(fy, start, end):
            raise validation(f"Budgets of {fy.display_name} can only be used when the event is inside that Fiscal Year "
                             f"or within {WINDOW_MONTHS} months of its start or end.", "budget_ids")
        chosen.append((b, fy))
    fys = list({fy.id: fy for _b, fy in chosen}.values())
    if len(fys) > MAX_FISCAL_YEARS:
        raise validation("A fundraiser can use budgets of at most two Fiscal Years.", "budget_ids")
    if len(fys) == 2 and not _adjacent(db, ctx.workspace_id, fys[0], fys[1]):
        raise validation("The two Fiscal Years of a fundraiser must follow each other.", "budget_ids")
    if f is not None:  # budgets of a closed Fiscal Year are frozen
        new_ids = {b.id for b, _fy in chosen}
        for fb in f.budgets:
            fy = db.get(FiscalYear, fb.fiscal_year_id)
            if fy.status == "CLOSED" and fb.budget_id not in new_ids:
                raise AppError(409, "FISCAL_YEAR_CLOSED", f"{fy.display_name} is closed; its budget for this "
                               "fundraiser cannot be removed or changed.")
    return chosen


# ------------------------------------------------------------------ CRUD
def snapshot(f: Fundraiser) -> dict:
    return {"id": f.id, "name": f.name, "description": f.description, "start_date": f.start_date.isoformat(),
            "end_date": f.end_date.isoformat(), "filter_text": f.filter_text, "filter_regex": bool(f.filter_regex),
            "budget_ids": [fb.budget_id for fb in f.budgets], "archived": f.archived_at is not None,
            "cancelled": f.cancelled_at is not None, "cancel_reason": f.cancel_reason,
            "cancelled_at": f.cancelled_at.isoformat() + "Z" if f.cancelled_at else None,
            "summary_notes": f.summary_notes, "results_final": f.results_final_at is not None,
            "series_id": f.series_id, "continues_from_id": f.continues_from_id}


def _apply(db: Session, ctx, f: Fundraiser, body, creating: bool) -> None:
    start, end = body.start_date, body.end_date or body.start_date
    if creating or (start, end) != (f.start_date, f.end_date):
        check_event_dates(db, ctx.workspace_id, start, end)
    compile_filter(body.filter_text, bool(body.filter_regex))
    chosen = _validate_budgets(db, ctx, None if creating else f, start, end, body.budget_ids)
    if not creating:  # moving the event must keep frozen (closed-FY) budgets valid
        for fb in f.budgets:
            fy = db.get(FiscalYear, fb.fiscal_year_id)
            if fy.status == "CLOSED" and not in_window(fy, start, end):
                raise validation(f"The new dates are too far from {fy.display_name}, whose budget is part of this "
                                 "fundraiser and can no longer change.", "start_date")
    f.name, f.description = body.name, body.description or None
    f.start_date, f.end_date = start, end
    f.filter_text = (body.filter_text or "").strip() or None
    f.filter_regex = bool(body.filter_regex) and f.filter_text is not None
    f.updated_by_user_id = ctx.user.id
    want = {(fy.id, b.budget_type): b for b, fy in chosen}
    for fb in list(f.budgets):
        b = want.pop((fb.fiscal_year_id, fb.kind), None)
        if b is None:
            f.budgets.remove(fb)
        else:
            fb.budget_id = b.id
    for (fy_id, kind), b in want.items():
        f.budgets.append(FundraiserBudget(fiscal_year_id=fy_id, budget_id=b.id, kind=kind))


def create(db: Session, ctx, body) -> Fundraiser:
    f = Fundraiser(workspace_id=ctx.workspace_id, created_by_user_id=ctx.user.id, start_date=body.start_date,
                   end_date=body.end_date or body.start_date, name=body.name)
    _apply(db, ctx, f, body, creating=True)
    db.add(f)
    db.flush()
    # 2.1.0 (#277): "Continues from" and "Create next year's from this one"
    from . import fundraiser_series as series
    if getattr(body, "continues_from_id", None):
        series.set_link(db, ctx, f, body.continues_from_id, record=False)
    if getattr(body, "copy_buckets_from_id", None):
        src = get(db, ctx, body.copy_buckets_from_id)
        series.copy_buckets(db, ctx, src, f)
    audit.record(db, ctx, "FUNDRAISER_CREATED", "fundraiser", f.id, None, snapshot(f))
    return f


def update(db: Session, ctx, f: Fundraiser, body) -> Fundraiser:
    before = snapshot(f)
    _apply(db, ctx, f, body, creating=False)
    db.flush()
    if "continues_from_id" in body.model_fields_set and body.continues_from_id != f.continues_from_id:
        from . import fundraiser_series as series
        series.set_link(db, ctx, f, body.continues_from_id)
    after = snapshot(f)
    if set(after["budget_ids"]) != set(before["budget_ids"]):
        dropped = _drop_orphan_adjustments(db, f)
        if dropped:
            after = {**after, "dropped_line_adjustments": dropped}
    if after != before:
        audit.record(db, ctx, "FUNDRAISER_UPDATED", "fundraiser", f.id, before, after)
    return f


def set_archived(db: Session, ctx, f: Fundraiser, archived: bool) -> Fundraiser:
    if (f.archived_at is not None) == archived:
        return f
    before = snapshot(f)
    f.archived_at = utcnow() if archived else None
    f.archived_by_user_id = ctx.user.id if archived else None
    audit.record(db, ctx, "FUNDRAISER_ARCHIVED" if archived else "FUNDRAISER_RESTORED", "fundraiser", f.id, before,
                 snapshot(f))
    return f


def set_cancelled(db: Session, ctx, f: Fundraiser, cancelled: bool, reason: str | None = None) -> Fundraiser:
    """v1.6.4 CR-037: mark that the fundraiser did not take place as planned (reason required) or reinstate it.
    Nothing else changes - its transactions, buckets and documents keep counting and working."""
    _require_open(db, ctx, f)
    if (f.cancelled_at is not None) == cancelled:
        raise AppError(409, "INVALID_STATE", "The fundraiser is already cancelled." if cancelled else "The fundraiser is not cancelled.")
    before = snapshot(f)
    if cancelled:
        reason = (reason or "").strip()
        if not reason:
            raise validation("A reason is required to cancel a fundraiser.", "reason")
        f.cancelled_at, f.cancelled_by_user_id, f.cancel_reason = utcnow(), ctx.user.id, reason
    else:
        f.cancelled_at = f.cancelled_by_user_id = f.cancel_reason = None
    db.flush()
    audit.record(db, ctx, "FUNDRAISER_CANCELLED" if cancelled else "FUNDRAISER_REINSTATED", "fundraiser", f.id, before,
                 snapshot(f))
    return f


def delete(db: Session, ctx, f: Fundraiser) -> None:
    """Allowed while nothing has been classified, excluded, bucketed or attached in the module. Otherwise: archive."""
    if any(fy.status == "CLOSED" for fy in _fys_of(db, f)):
        raise AppError(409, "FISCAL_YEAR_CLOSED", "A fundraiser using a closed Fiscal Year cannot be deleted; archive it.")
    if has_management_data(db, f):
        raise AppError(409, "FUNDRAISER_IN_USE", "This fundraiser has buckets or categories, special classifications, exclusions or "
                       "documents. Archive it instead (or remove those first).")
    audit.record(db, ctx, "FUNDRAISER_DELETED", "fundraiser", f.id, snapshot(f), None)
    db.delete(f)


def get(db: Session, ctx, fid: int) -> Fundraiser:
    return get_scoped(db, Fundraiser, fid, ctx, "Fundraiser")


# ------------------------------------------------------------------ derived figures
def _fys_of(db: Session, f: Fundraiser) -> list[FiscalYear]:
    ids = sorted({fb.fiscal_year_id for fb in f.budgets})
    return sorted((db.get(FiscalYear, i) for i in ids), key=lambda y: y.start_date)


def status_of(f: Fundraiser, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    if f.archived_at is not None:
        return "ARCHIVED"
    if f.cancelled_at is not None:  # v1.6.4 CR-037
        return "CANCELLED"
    if today < f.start_date:
        return "PLANNED"
    if today <= f.end_date:
        return "IN_PROGRESS"
    return "ENDED"


def touched_fy_ids(db: Session, ws_id: int, f: Fundraiser, fys: list[FiscalYear] | None = None) -> set[int]:
    fys = fys if fys is not None else _all_fys(db, ws_id)
    ids = {fb.fiscal_year_id for fb in f.budgets}
    ids |= {fy.id for fy in fys if fy.start_date <= f.end_date and fy.end_date >= f.start_date}
    return ids


def _lines(db: Session, f: Fundraiser) -> tuple[list[dict], int]:
    """Included allocation lines (+ the number of lines in the budgets that the filter left out)."""
    pred = compile_filter(f.filter_text, bool(f.filter_regex))
    kind_of: dict[int, tuple[str, int]] = {}
    for fb in f.budgets:
        b = db.get(Budget, fb.budget_id)
        for lid in leaf_ids(db, b):
            kind_of[lid] = (fb.kind, fb.fiscal_year_id)
    if not kind_of:
        return [], 0
    q = (select(TransactionAllocation, RegisterTransaction)
         .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
         .where(TransactionAllocation.budget_id.in_(list(kind_of)), TransactionAllocation.removed_at.is_(None),
                RegisterTransaction.status == "ACTIVE")
         .order_by(RegisterTransaction.transaction_date, RegisterTransaction.id, TransactionAllocation.id))
    excl = {x.allocation_id: x for x in db.scalars(select(FundraiserExclusion).where(FundraiserExclusion.fundraiser_id == f.id))}
    cls = {x.allocation_id: x for x in db.scalars(select(FundraiserClassification).where(FundraiserClassification.fundraiser_id == f.id))}
    assigned: dict[int, list[FundraiserBucketLine]] = defaultdict(list)
    for bl in db.scalars(select(FundraiserBucketLine).join(FundraiserBucket, FundraiserBucket.id == FundraiserBucketLine.bucket_id)
                         .where(FundraiserBucket.fundraiser_id == f.id).order_by(FundraiserBucketLine.id)):
        assigned[bl.allocation_id].append(bl)
    rows, skipped = [], 0
    for a, t in db.execute(q):
        if pred is not None and not pred(a.description or ""):
            skipped += 1
            continue
        kind, fy_id = kind_of[a.budget_id]
        ex, c = excl.get(a.id), cls.get(a.id)
        classified = 0 if (ex or c is None) else min(c.amount_cents, a.amount_cents)  # clamp if the line shrank later
        eff = 0 if ex else a.amount_cents - classified
        buckets = [] if ex else assigned.get(a.id, [])
        rows.append({"a": a, "t": t, "kind": kind, "fiscal_year_id": fy_id, "excluded": ex, "classification": c,
                     "classified": classified, "eff": eff, "buckets": buckets,
                     "unassigned": max(0, eff - sum(b.amount_cents for b in buckets))})
    return rows, skipped


def has_management_data(db: Session, f: Fundraiser) -> bool:
    for model in (FundraiserExclusion, FundraiserClassification, FundraiserBucket, FundraiserBucketCategory):
        if db.scalar(select(model.id).where(model.fundraiser_id == f.id).limit(1)) is not None:
            return True
    return db.scalar(select(Attachment.id).where(Attachment.fundraiser_id == f.id, Attachment.active.is_(True)).limit(1)) is not None


def _drop_orphan_adjustments(db: Session, f: Fundraiser) -> int:
    """After a budget was removed/changed: adjustments of lines that are no longer in the fundraiser's budgets."""
    leafs: set[int] = set()
    for fb in f.budgets:
        leafs |= set(leaf_ids(db, db.get(Budget, fb.budget_id)))
    n = 0
    bucket_ids = list(db.scalars(select(FundraiserBucket.id).where(FundraiserBucket.fundraiser_id == f.id)))
    items = [*db.scalars(select(FundraiserExclusion).where(FundraiserExclusion.fundraiser_id == f.id)),
             *db.scalars(select(FundraiserClassification).where(FundraiserClassification.fundraiser_id == f.id)),
             *(db.scalars(select(FundraiserBucketLine).where(FundraiserBucketLine.bucket_id.in_(bucket_ids))) if bucket_ids else [])]
    for x in items:
        a = db.get(TransactionAllocation, x.allocation_id)
        if a is None or a.budget_id not in leafs:
            db.delete(x)
            n += 1
    return n


def preview(db: Session, ctx, budget_ids: list[int], filter_text: str | None, filter_regex: bool) -> dict:
    """Live preview for the create/edit form: how many lines the budgets hold and how many match the filter."""
    pred = compile_filter(filter_text, filter_regex)
    leafs: list[int] = []
    for bid in dict.fromkeys(budget_ids):
        b = db.get(Budget, bid)
        fy = db.get(FiscalYear, b.fiscal_year_id) if b else None
        if b is None or fy is None or fy.workspace_id != ctx.workspace_id:
            raise not_found("Budget")
        leafs += leaf_ids(db, b)
    total = matched = 0
    samples: list[str] = []
    if leafs:
        q = (select(TransactionAllocation.description)
             .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
             .where(TransactionAllocation.budget_id.in_(leafs), TransactionAllocation.removed_at.is_(None),
                    RegisterTransaction.status == "ACTIVE"))
        for (desc,) in db.execute(q):
            total += 1
            if pred is None or pred(desc or ""):
                matched += 1
            elif len(samples) < 5 and desc:
                samples.append(desc)
    shared = _shared_with(db, ctx.workspace_id, set(leafs), exclude_id=None)
    return {"total_lines": total, "matched_lines": matched, "unmatched_samples": samples,
            "shared_with": [{"id": x.id, "name": x.name} for x in shared]}


def _shared_with(db: Session, ws_id: int, leafs: set[int], exclude_id: int | None) -> list[Fundraiser]:
    if not leafs:
        return []
    out = []
    for other in db.scalars(select(Fundraiser).where(Fundraiser.workspace_id == ws_id, Fundraiser.archived_at.is_(None))):
        if other.id == exclude_id:
            continue
        theirs: set[int] = set()
        for fb in other.budgets:
            theirs |= set(leaf_ids(db, db.get(Budget, fb.budget_id)))
        if theirs & leafs:
            out.append(other)
    return out


def _money_totals(rows: list[dict]) -> dict:
    """Fundraiser income/expense = line amounts without excluded lines and without classified (cash float) amounts."""
    inc = sum(r["eff"] for r in rows if r["kind"] == "INCOME")
    exp = sum(r["eff"] for r in rows if r["kind"] == "EXPENSE")
    return {"income": inc, "expense": exp, "net": inc - exp}


def roi(income: int, expense: int) -> str | None:
    """Return on investment = net ÷ expense (None without expenses)."""
    return None if expense == 0 else f"{(income - expense) / expense:.4f}"


def notices(db: Session, ws_id: int, f: Fundraiser) -> list[dict]:
    out = []
    used = {fb.fiscal_year_id: set() for fb in f.budgets}
    for fb in f.budgets:
        used[fb.fiscal_year_id].add(fb.kind)
    fys = _all_fys(db, ws_id)
    if not f.budgets:
        out.append({"code": "NO_BUDGETS", "message": "No budgets selected yet. Select the income and/or expense budget "
                    "once the Fiscal Year and its budgets are set up."})
    if len(used) < MAX_FISCAL_YEARS:
        for fy in fys:
            if fy.id in used or fy.status == "CLOSED" or not in_window(fy, f.start_date, f.end_date):
                continue
            if used and not _adjacent(db, ws_id, fy, db.get(FiscalYear, next(iter(used)))):
                continue
            if f.budgets:
                out.append({"code": "FY_WITHOUT_BUDGET", "fiscal_year_id": fy.id,
                            "message": f"The event is within {WINDOW_MONTHS} months of {fy.display_name} — its budgets "
                                       "can also be selected for this fundraiser."})
        # a Fiscal Year within the window that is not set up yet (typically next year's)
        last_end = max((fy.end_date for fy in fys), default=None)
        if last_end is not None and add_months(f.end_date, WINDOW_MONTHS) > last_end:
            out.append({"code": "FUTURE_FY", "message": f"The event is within {WINDOW_MONTHS} months of a Fiscal Year "
                        "that is not set up yet — select its budgets once that Fiscal Year exists (Draft or later)."})
    for fb in f.budgets:
        b = db.get(Budget, fb.budget_id)
        for w in budget_warnings(db, b):
            out.append({**w, "budget_id": b.id})
    if f.filter_text:
        out.append({"code": "FILTER", "message": "A description filter is used: only lines whose description contains "
                    "the filter are included. Lines entered without it are left out, which affects the validity of the "
                    "figures."})
    leafs: set[int] = set()
    for fb in f.budgets:
        leafs |= set(leaf_ids(db, db.get(Budget, fb.budget_id)))
    shared = _shared_with(db, ws_id, leafs, exclude_id=f.id)
    if shared:
        out.append({"code": "SHARED_BUDGET", "message": "Another fundraiser uses the same budget(s): "
                    + ", ".join(x.name for x in shared) + ". Their totals overlap unless their filters separate them."})
    return out


def list_out(db: Session, ctx, fiscal_year_id: int | None, upcoming: bool, include_archived: bool) -> list[dict]:
    fys = _all_fys(db, ctx.workspace_id)
    q = select(Fundraiser).where(Fundraiser.workspace_id == ctx.workspace_id).order_by(Fundraiser.start_date, Fundraiser.name)
    if not include_archived:
        q = q.where(Fundraiser.archived_at.is_(None))
    out = []
    for f in db.scalars(q):
        touched = touched_fy_ids(db, ctx.workspace_id, f, fys)
        if upcoming:
            if touched:
                continue
        elif fiscal_year_id is not None and fiscal_year_id not in touched:
            continue
        rows, _skipped = _lines(db, f)
        t = _money_totals(rows)
        my_fys = [fy for fy in fys if fy.id in {fb.fiscal_year_id for fb in f.budgets}]
        out.append({**snapshot(f), "status": status_of(f), "fiscal_years": [fy_brief(y) for y in my_fys],
                    "income": fmt(t["income"]), "expense": fmt(t["expense"]), "net": fmt(t["net"]),
                    "has_budgets": bool(f.budgets)})
    return out


def detail(db: Session, ctx, f: Fundraiser) -> dict:
    rows, skipped = _lines(db, f)
    t = _money_totals(rows)
    fys = _fys_of(db, f)
    per_fy = []
    for fy in fys:
        sub = [r for r in rows if r["fiscal_year_id"] == fy.id]
        st = _money_totals(sub)
        per_fy.append({"fiscal_year": fy_brief(fy), "income": fmt(st["income"]), "expense": fmt(st["expense"]),
                       "net": fmt(st["net"]), "read_only": fy.status == "CLOSED"})
    accounts = {a.id: a for a in db.scalars(select(BankAccount).where(BankAccount.workspace_id == ctx.workspace_id))}
    t_ids = sorted({r["t"].id for r in rows})
    a_ids = [r["a"].id for r in rows]
    atts: dict[tuple[str, int], list[dict]] = defaultdict(list)
    if rows:
        q = select(Attachment).where(Attachment.active.is_(True),
                                     (Attachment.transaction_id.in_(t_ids)) | (Attachment.allocation_id.in_(a_ids)))
        for x in db.scalars(q.order_by(*DISPLAY_ORDER)):  # 2.1.0 (#259)
            key = ("a", x.allocation_id) if x.allocation_id else ("t", x.transaction_id)
            atts[key].append({"id": x.id, "original_filename": x.original_filename, "mime_type": x.mime_type,
                              "size_bytes": x.size_bytes, "content_url": f"/api/attachments/{x.id}/content"})
    budget_cache: dict[int, dict] = {}
    closed_fy = {fy.id: fy.status == "CLOSED" for fy in fys}
    lines = []
    for r in rows:
        a, tx = r["a"], r["t"]
        if a.budget_id not in budget_cache:
            budget_cache[a.budget_id] = budget_brief(db, db.get(Budget, a.budget_id))
        acct = accounts.get(tx.bank_account_id)
        ent = a.entity or tx.parent_entity
        lines.append({
            "allocation_id": a.id, "transaction_id": tx.id, "kind": r["kind"], "fiscal_year_id": r["fiscal_year_id"],
            "transaction_date": tx.transaction_date.isoformat(), "transaction_type": tx.transaction_type,
            "bank_account_id": tx.bank_account_id,
            "bank_account": f"{acct.account_name} - {bank.masked(acct)}" if acct else None,
            "entity": ent.display_name if ent else None, "description": a.description, "check_number": tx.check_number,
            "amount": fmt(a.amount_cents), "budget": budget_cache[a.budget_id]["label"],
            "cleared": tx.clear_date is not None,
            "attachments": atts.get(("t", tx.id), []) + atts.get(("a", a.id), []),
            # v1.6.1 CR-034
            "excluded": r["excluded"] is not None,
            "exclusion_reason": r["excluded"].reason if r["excluded"] else None,
            "classification": None if r["classification"] is None or r["excluded"] else {
                "kind": r["classification"].kind, "label": CLASSIFICATIONS[r["classification"].kind][1],
                "amount": fmt(r["classified"]), "note": r["classification"].note},
            "counted": fmt(r["eff"]),
            "buckets": [bucket_line_out(b) for b in r["buckets"]],
            "unassigned": fmt(r["unassigned"]),
            "over_assigned": sum(b.amount_cents for b in r["buckets"]) > r["eff"],
            "read_only": closed_fy.get(r["fiscal_year_id"], False),
        })
    # cumulative income / expense from the first included transaction to the last (by transaction date)
    by_day: dict[str, list[int]] = {}
    for r in rows:
        d = r["t"].transaction_date.isoformat()
        if r["excluded"]:
            continue
        by_day.setdefault(d, [0, 0])[0 if r["kind"] == "INCOME" else 1] += r["eff"]
    cum, inc, exp = [], 0, 0
    for d in sorted(by_day):
        inc += by_day[d][0]
        exp += by_day[d][1]
        cum.append({"date": d, "income": fmt(inc), "expense": fmt(exp), "net": fmt(inc - exp)})
    selected = []
    for fb in f.budgets:
        b = db.get(Budget, fb.budget_id)
        selected.append({**budget_brief(db, b), "kind": fb.kind, "fiscal_year": fy_brief(db.get(FiscalYear, fb.fiscal_year_id))})
    all_closed = bool(fys) and all(fy.status == "CLOSED" for fy in fys)
    if not fys:
        all_closed = any(fy.status == "CLOSED" for fy in covering_fiscal_years(db, ctx.workspace_id, f.start_date))
    return {
        **snapshot(f), "status": status_of(f), "fiscal_years": [fy_brief(y) for y in fys],
        "budgets": sorted(selected, key=lambda x: (x["fiscal_year"]["start_date"], x["kind"] != "INCOME")),
        "read_only": all_closed,
        "notices": notices(db, ctx.workspace_id, f),
        "totals": {"income": fmt(t["income"]), "expense": fmt(t["expense"]), "net": fmt(t["net"]),
                   "roi": roi(t["income"], t["expense"]),
                   "cash_float_out": fmt(sum(r["classified"] for r in rows if r["kind"] == "EXPENSE")),
                   "cash_float_returned": fmt(sum(r["classified"] for r in rows if r["kind"] == "INCOME")),
                   "excluded_income": fmt(sum(r["a"].amount_cents for r in rows if r["excluded"] and r["kind"] == "INCOME")),
                   "excluded_expense": fmt(sum(r["a"].amount_cents for r in rows if r["excluded"] and r["kind"] == "EXPENSE")),
                   "excluded_lines": sum(1 for r in rows if r["excluded"])},
        "buckets": _bucket_summary(db, f, rows),
        "report_status": _report_status(db, f),
        "series_link": _series_link(db, f),
        "classification_types": [{"kind": k, "applies_to": v[0], "label": v[1]} for k, v in CLASSIFICATIONS.items()],
        "per_fiscal_year": per_fy,
        "lines": lines, "filtered_out_lines": skipped,
        "cumulative": cum,
    }


# ------------------------------------------------------------------ v1.6.1 CR-034: buckets, classifications, exclusions
def bucket_line_out(b: FundraiserBucketLine) -> dict:
    """A bucket's part of a line: the net (amount) and, 2.1.0 (#278), the charge and the credit taken off it."""
    charge = b.charge_cents if b.charge_cents is not None else b.amount_cents
    return {"bucket_id": b.bucket_id, "amount": fmt(b.amount_cents), "charge": fmt(charge),
            "less": fmt(b.less_cents or 0), "less_description": b.less_description,
            "contributor_override": b.contributor_override}


def ordered_buckets(db: Session, f: Fundraiser) -> list[FundraiserBucket]:
    """Display order (2.1.0 #278); buckets without one (none after migration 0039) after them by name."""
    bs = list(db.scalars(select(FundraiserBucket).where(FundraiserBucket.fundraiser_id == f.id)))
    return sorted(bs, key=lambda b: (b.display_order is None, b.display_order or 0, b.name, b.id))


def ordered_categories(db: Session, f: Fundraiser) -> list[FundraiserBucketCategory]:
    return list(db.scalars(select(FundraiserBucketCategory).where(FundraiserBucketCategory.fundraiser_id == f.id)
                           .order_by(FundraiserBucketCategory.display_order, FundraiserBucketCategory.id)))


def _bucket_summary(db: Session, f: Fundraiser, rows: list[dict]) -> dict:
    """Buckets in display order with their income, expense and net; 2.1.0 (#278) also the categories (in order, each
    with its buckets and subtotals). Uncategorized buckets are listed after the categories."""
    buckets = ordered_buckets(db, f)
    agg = {b.id: {"INCOME": 0, "EXPENSE": 0, "lines": 0, "less_INCOME": 0, "less_EXPENSE": 0} for b in buckets}
    un = {"INCOME": 0, "EXPENSE": 0}
    for r in rows:
        if r["excluded"]:
            continue
        un[r["kind"]] += r["unassigned"]
        for bl in r["buckets"]:
            if bl.bucket_id in agg:
                agg[bl.bucket_id][r["kind"]] += bl.amount_cents
                agg[bl.bucket_id]["lines"] += 1
                agg[bl.bucket_id]["less_" + r["kind"]] += bl.less_cents or 0
    cats = ordered_categories(db, f)
    cat_ids = {c.id for c in cats}

    def item(b: FundraiserBucket) -> dict:
        g = agg[b.id]
        return {"id": b.id, "name": b.name, "description": b.description, "income": fmt(g["INCOME"]),
                "expense": fmt(g["EXPENSE"]), "net": fmt(g["INCOME"] - g["EXPENSE"]), "lines": g["lines"],
                "credits_income": fmt(g["less_INCOME"]), "credits_expense": fmt(g["less_EXPENSE"]),
                "category_id": b.category_id if b.category_id in cat_ids else None,
                "display_order": b.display_order}

    items = [item(b) for b in buckets]
    categories = []
    for c in cats:
        mine = [x for x in items if x["category_id"] == c.id]
        inc = sum(agg[x["id"]]["INCOME"] for x in mine)
        exp = sum(agg[x["id"]]["EXPENSE"] for x in mine)
        categories.append({"id": c.id, "name": c.name, "description": c.description, "display_order": c.display_order,
                           "bucket_ids": [x["id"] for x in mine], "income": fmt(inc), "expense": fmt(exp),
                           "net": fmt(inc - exp), "lines": sum(x["lines"] for x in mine)})
    return {"items": items, "categories": categories,
            "uncategorized_ids": [x["id"] for x in items if x["category_id"] is None],
            "unassigned": {"income": fmt(un["INCOME"]), "expense": fmt(un["EXPENSE"]),
                           "net": fmt(un["INCOME"] - un["EXPENSE"])}}


def _bucket_snapshot(b: FundraiserBucket) -> dict:
    return {"id": b.id, "fundraiser_id": b.fundraiser_id, "name": b.name, "description": b.description,
            "category_id": b.category_id, "display_order": b.display_order}


def _check_category(db: Session, f: Fundraiser, category_id: int | None) -> None:
    if category_id is not None:
        get_category(db, f, category_id)


def _next_bucket_order(db: Session, f: Fundraiser) -> int:
    return max([b.display_order or 0 for b in ordered_buckets(db, f)] or [0]) + 1


def _check_bucket_name(db: Session, f: Fundraiser, name: str, exclude_id: int | None) -> None:
    for b in db.scalars(select(FundraiserBucket).where(FundraiserBucket.fundraiser_id == f.id)):
        if b.id != exclude_id and b.name.casefold() == name.casefold():
            raise validation("This fundraiser already has a bucket with that name.", "name")


def _require_open(db: Session, ctx, f: Fundraiser) -> None:
    fys = _fys_of(db, f)
    if fys and all(fy.status == "CLOSED" for fy in fys):
        raise AppError(409, "FISCAL_YEAR_CLOSED", "The Fiscal Year of this fundraiser is closed; it can no longer be changed.")


def create_bucket(db: Session, ctx, f: Fundraiser, body) -> FundraiserBucket:
    _require_open(db, ctx, f)
    n = len(list(db.scalars(select(FundraiserBucket.id).where(FundraiserBucket.fundraiser_id == f.id))))
    if n >= MAX_BUCKETS:
        raise validation(f"A fundraiser can have at most {MAX_BUCKETS} buckets.", "name")
    _check_bucket_name(db, f, body.name, None)
    _check_category(db, f, body.category_id)
    b = FundraiserBucket(fundraiser_id=f.id, name=body.name, description=body.description or None,
                         category_id=body.category_id, display_order=_next_bucket_order(db, f),
                         created_by_user_id=ctx.user.id)
    db.add(b)
    db.flush()
    audit.record(db, ctx, "FUNDRAISER_BUCKET_CREATED", "fundraiser_bucket", b.id, None, _bucket_snapshot(b))
    return b


def get_bucket(db: Session, f: Fundraiser, bucket_id: int) -> FundraiserBucket:
    b = db.get(FundraiserBucket, bucket_id)
    if b is None or b.fundraiser_id != f.id:
        raise not_found("Bucket")
    return b


def update_bucket(db: Session, ctx, f: Fundraiser, b: FundraiserBucket, body) -> FundraiserBucket:
    """Name and description follow the closed-year rule; the category (presentation only, #278) can always change."""
    if (body.name, body.description or None) != (b.name, b.description):
        _require_open(db, ctx, f)
    _check_bucket_name(db, f, body.name, b.id)
    _check_category(db, f, body.category_id)
    before = _bucket_snapshot(b)
    b.name, b.description, b.category_id = body.name, body.description or None, body.category_id
    db.flush()
    if _bucket_snapshot(b) != before:
        audit.record(db, ctx, "FUNDRAISER_BUCKET_UPDATED", "fundraiser_bucket", b.id, before, _bucket_snapshot(b))
    return b


def delete_bucket(db: Session, ctx, f: Fundraiser, b: FundraiserBucket) -> None:
    """Removes the bucket and its assignments (the lines become unassigned). Refused when it holds lines of a closed
    Fiscal Year."""
    lines = list(db.scalars(select(FundraiserBucketLine).where(FundraiserBucketLine.bucket_id == b.id)))
    for bl in lines:
        a = db.get(TransactionAllocation, bl.allocation_id)
        if a is not None and db.get(FiscalYear, a.budget.fiscal_year_id).status == "CLOSED":
            raise AppError(409, "FISCAL_YEAR_CLOSED", "This bucket holds lines of a closed Fiscal Year and cannot be deleted.")
    audit.record(db, ctx, "FUNDRAISER_BUCKET_DELETED", "fundraiser_bucket", b.id,
                 {**_bucket_snapshot(b), "assignments": [{"allocation_id": x.allocation_id, "amount": fmt(x.amount_cents)} for x in lines]}, None)
    for bl in lines:
        db.delete(bl)
    db.flush()  # assignments first (no ORM relationship orders these deletes)
    db.delete(b)


def _line_state(db: Session, f: Fundraiser, allocation_id: int) -> dict:
    ex = db.scalar(select(FundraiserExclusion).where(FundraiserExclusion.fundraiser_id == f.id,
                                                     FundraiserExclusion.allocation_id == allocation_id))
    c = db.scalar(select(FundraiserClassification).where(FundraiserClassification.fundraiser_id == f.id,
                                                         FundraiserClassification.allocation_id == allocation_id))
    bls = list(db.scalars(select(FundraiserBucketLine).join(FundraiserBucket, FundraiserBucket.id == FundraiserBucketLine.bucket_id)
                          .where(FundraiserBucket.fundraiser_id == f.id, FundraiserBucketLine.allocation_id == allocation_id)
                          .order_by(FundraiserBucketLine.bucket_id)))
    return {"ex": ex, "c": c, "bls": bls}


def _line_snapshot(st: dict) -> dict:
    return {"excluded": st["ex"] is not None, "exclusion_reason": st["ex"].reason if st["ex"] else None,
            "classification": None if st["c"] is None else {"kind": st["c"].kind, "amount": fmt(st["c"].amount_cents),
                                                           "note": st["c"].note},
            "buckets": [bucket_line_out(x) for x in st["bls"]]}


def set_line(db: Session, ctx, f: Fundraiser, allocation_id: int, body) -> None:
    """Sets the whole fundraiser state of one line: excluded (with reason) OR an optional cash-float classification
    (amount <= line) plus bucket assignments (sum <= line - classified)."""
    rows, _skipped = _lines(db, f)
    row = next((r for r in rows if r["a"].id == allocation_id), None)
    if row is None:
        raise not_found("Fundraiser line")
    fy = db.get(FiscalYear, row["fiscal_year_id"])
    if fy.status == "CLOSED":
        raise AppError(409, "FISCAL_YEAR_CLOSED", f"{fy.display_name} is closed; this line can no longer be changed.")
    amount = row["a"].amount_cents
    st = _line_state(db, f, allocation_id)
    before = _line_snapshot(st)

    def cents(value, field):
        try:
            return parse_amount(value, allow_zero=False)
        except ValueError as e:
            raise validation(str(e).capitalize() + ".", field) from None

    if body.excluded:
        reason = (body.exclusion_reason or "").strip()
        if not reason:
            raise validation("A reason is required to exclude a line.", "exclusion_reason")
        if body.classification is not None or body.buckets:
            raise validation("An excluded line cannot have a classification or buckets.", "excluded")
        if st["ex"] is None:
            db.add(FundraiserExclusion(fundraiser_id=f.id, allocation_id=allocation_id, reason=reason,
                                       created_by_user_id=ctx.user.id))
        else:
            st["ex"].reason = reason
        if st["c"] is not None:
            db.delete(st["c"])
        for bl in st["bls"]:
            db.delete(bl)
    else:
        if st["ex"] is not None:
            db.delete(st["ex"])
        classified = 0
        if body.classification is None:
            if st["c"] is not None:
                db.delete(st["c"])
        else:
            kind = body.classification.kind
            if CLASSIFICATIONS[kind][0] != row["kind"]:
                side = "an expense (withdrawal)" if CLASSIFICATIONS[kind][0] == "EXPENSE" else "an income (deposit)"
                raise validation(f"“{CLASSIFICATIONS[kind][1]}” applies to {side} line.", "classification")
            classified = cents(body.classification.amount, "classification")
            if classified > amount:
                raise validation("The classified amount cannot be more than the line amount.", "classification")
            note = (body.classification.note or "").strip() or None
            if st["c"] is None:
                db.add(FundraiserClassification(fundraiser_id=f.id, allocation_id=allocation_id, kind=kind,
                                                amount_cents=classified, note=note, created_by_user_id=ctx.user.id))
            else:
                st["c"].kind, st["c"].amount_cents, st["c"].note = kind, classified, note
        want: dict[int, tuple[int, int, int, str | None]] = {}   # bucket -> (net, charge, less, less description)
        shown: dict[int, str | None] = {}                          # bucket -> contributor shown on the reports
        for item in body.buckets:
            get_bucket(db, f, item.bucket_id)
            if item.bucket_id in want:
                raise validation("A bucket can be listed only once per line.", "buckets")
            want[item.bucket_id] = _bucket_amounts(item, cents)
            shown[item.bucket_id] = (getattr(item, "contributor_override", None) or "").strip() or None
        if sum(v[0] for v in want.values()) > amount - classified:
            raise validation("The bucket amounts add up to more than the amount that counts for this line "
                             f"({fmt(amount - classified)}).", "buckets")
        for bl in st["bls"]:
            if bl.bucket_id in want:
                bl.amount_cents, bl.charge_cents, bl.less_cents, bl.less_description = want.pop(bl.bucket_id)
                bl.contributor_override = shown[bl.bucket_id]
            else:
                db.delete(bl)
        for bucket_id, (net, charge, less, desc) in want.items():
            db.add(FundraiserBucketLine(bucket_id=bucket_id, allocation_id=allocation_id, amount_cents=net,
                                        charge_cents=charge, less_cents=less, less_description=desc,
                                        contributor_override=shown[bucket_id]))
    db.flush()
    after = _line_snapshot(_line_state(db, f, allocation_id))
    if after != before:
        audit.record(db, ctx, "FUNDRAISER_LINE_UPDATED", "fundraiser", f.id,
                     {"allocation_id": allocation_id, **before}, {"allocation_id": allocation_id, **after})


def _bucket_amounts(item, cents) -> tuple[int, int, int, str | None]:
    """2.1.0 (#278): (net, charge, less, less description). `amount` alone (as before) = a charge with no credit.
    Charge > 0; 0 <= Less <= Charge (a fully credited item nets $0); a Less needs its description."""
    if item.charge is None:
        if item.less is not None or item.less_description:
            raise validation("Enter the Charge when a Less amount is given.", "buckets")
        if item.amount is None:
            raise validation("Enter the amount (or the Charge) for each bucket.", "buckets")
        c = cents(item.amount, "buckets")
        return c, c, 0, None
    charge = cents(item.charge, "buckets")
    try:
        less = parse_amount(item.less, allow_zero=True) if item.less not in (None, "") else 0
    except ValueError as e:
        raise validation(str(e).capitalize() + ".", "buckets") from None
    if less < 0:
        raise validation("The Less amount cannot be negative.", "buckets")
    if less > charge:
        raise validation("The Less amount cannot be more than the Charge.", "buckets")
    desc = (item.less_description or "").strip() or None
    if less > 0 and not desc:
        raise validation("Describe the Less amount (for example “Pre-paid team credit”).", "less_description")
    if less == 0:
        desc = None
    net = charge - less
    if item.amount is not None and cents(item.amount, "buckets") != net:
        raise validation("The amount must equal the Charge less the Less amount.", "buckets")
    return net, charge, less, desc


# ------------------------------------------------------------------ 2.1.0 (#278): bucket categories and display order
def _category_snapshot(c: FundraiserBucketCategory) -> dict:
    return {"id": c.id, "fundraiser_id": c.fundraiser_id, "name": c.name, "description": c.description,
            "display_order": c.display_order}


def get_category(db: Session, f: Fundraiser, category_id: int) -> FundraiserBucketCategory:
    c = db.get(FundraiserBucketCategory, category_id)
    if c is None or c.fundraiser_id != f.id:
        raise not_found("Category")
    return c


def _check_category_name(db: Session, f: Fundraiser, name: str, exclude_id: int | None) -> None:
    for c in ordered_categories(db, f):
        if c.id != exclude_id and c.name.casefold() == name.casefold():
            raise validation("This fundraiser already has a category with that name.", "name")


def create_category(db: Session, ctx, f: Fundraiser, body) -> FundraiserBucketCategory:
    """Categories only arrange buckets on the page and in the reports, so they can change in a closed year too."""
    cats = ordered_categories(db, f)
    if len(cats) >= MAX_CATEGORIES:
        raise validation(f"A fundraiser can have at most {MAX_CATEGORIES} categories.", "name")
    _check_category_name(db, f, body.name, None)
    c = FundraiserBucketCategory(fundraiser_id=f.id, name=body.name, description=body.description or None,
                                 display_order=max([x.display_order for x in cats] or [0]) + 1,
                                 created_by_user_id=ctx.user.id)
    db.add(c)
    db.flush()
    audit.record(db, ctx, "FUNDRAISER_CATEGORY_CREATED", "fundraiser_bucket_category", c.id, None, _category_snapshot(c))
    return c


def update_category(db: Session, ctx, f: Fundraiser, c: FundraiserBucketCategory, body) -> FundraiserBucketCategory:
    _check_category_name(db, f, body.name, c.id)
    before = _category_snapshot(c)
    c.name, c.description = body.name, body.description or None
    db.flush()
    if _category_snapshot(c) != before:
        audit.record(db, ctx, "FUNDRAISER_CATEGORY_UPDATED", "fundraiser_bucket_category", c.id, before,
                     _category_snapshot(c))
    return c


def delete_category(db: Session, ctx, f: Fundraiser, c: FundraiserBucketCategory) -> None:
    """Its buckets become uncategorized; no figure changes."""
    moved = list(db.scalars(select(FundraiserBucket).where(FundraiserBucket.fundraiser_id == f.id,
                                                           FundraiserBucket.category_id == c.id)))
    audit.record(db, ctx, "FUNDRAISER_CATEGORY_DELETED", "fundraiser_bucket_category", c.id,
                 {**_category_snapshot(c), "bucket_ids": [b.id for b in moved]}, None)
    for b in moved:
        b.category_id = None
    db.flush()
    db.delete(c)


def reorder(db: Session, ctx, f: Fundraiser, what: str, ids: list[int]) -> None:
    """Sets the display order of every category (what="categories") or bucket (what="buckets") of the fundraiser."""
    items = ordered_categories(db, f) if what == "categories" else ordered_buckets(db, f)
    have = [x.id for x in items]
    if len(ids) != len(set(ids)) or sorted(ids) != sorted(have):
        raise validation(f"List every {what[:-1]} of this fundraiser exactly once.", "ids")
    if ids == have:
        return
    by = {x.id: x for x in items}
    before = [{"id": x.id, "name": x.name} for x in items]
    for i, x_id in enumerate(ids, start=1):
        by[x_id].display_order = i
    db.flush()
    audit.record(db, ctx, f"FUNDRAISER_{what.upper()}_REORDERED", "fundraiser", f.id, {"order": before},
                 {"order": [{"id": i, "name": by[i].name} for i in ids]})


# ------------------------------------------------------------------ 2.1.0 (#275): stakeholder report settings
def _report_status(db: Session, f: Fundraiser) -> dict:
    from .fundraiser_summary import report_status
    return report_status(db, f)


def _series_link(db: Session, f: Fundraiser) -> dict:
    """2.1.0 (#277): the series and the previous fundraiser this one continues."""
    from ..models import FundraiserSeries
    s = db.get(FundraiserSeries, f.series_id) if f.series_id else None
    prev = db.get(Fundraiser, f.continues_from_id) if f.continues_from_id else None
    return {"series": {"id": s.id, "name": s.name} if s else None,
            "continues_from": {"id": prev.id, "name": prev.name, "start_date": prev.start_date.isoformat()} if prev else None}


def set_summary_notes(db: Session, ctx, f: Fundraiser, notes: str | None) -> Fundraiser:
    """Budget Managers only (fundraiser.manage); printed under the key takeaways. Reporting text, so allowed in a
    closed year too."""
    notes = (notes or "").strip() or None
    if notes != f.summary_notes:
        before = f.summary_notes
        f.summary_notes = notes
        f.updated_by_user_id = ctx.user.id
        db.flush()
        audit.record(db, ctx, "FUNDRAISER_SUMMARY_NOTES_UPDATED", "fundraiser", f.id, {"summary_notes": before},
                     {"summary_notes": notes})
    return f


def set_results_final(db: Session, ctx, f: Fundraiser, final: bool) -> Fundraiser:
    """Mark results final (reversible). The report reads Final when marked, or when every Fiscal Year is Closed."""
    if final == (f.results_final_at is not None):
        return f
    before = {"results_final": f.results_final_at is not None,
              "results_final_at": f.results_final_at.isoformat() + "Z" if f.results_final_at else None}
    f.results_final_at = utcnow() if final else None
    f.results_final_by_user_id = ctx.user.id if final else None
    db.flush()
    audit.record(db, ctx, "FUNDRAISER_RESULTS_FINAL_MARKED" if final else "FUNDRAISER_RESULTS_FINAL_UNMARKED",
                 "fundraiser", f.id, before,
                 {"results_final": final, "results_final_at": f.results_final_at.isoformat() + "Z" if final else None})
    return f


# ------------------------------------------------------------------ v1.6.2 CR-035: report selection
def for_fiscal_year_report(db: Session, ws_id: int, fy: FiscalYear) -> list[Fundraiser]:
    """Fundraisers shown in a Fiscal Year's Audit / Close report: not archived, with a budget in that year."""
    if not module_enabled(db, ws_id):
        return []
    out = [f for f in db.scalars(select(Fundraiser).where(Fundraiser.workspace_id == ws_id, Fundraiser.archived_at.is_(None))
                                 .order_by(Fundraiser.start_date, Fundraiser.name, Fundraiser.id))
           if any(fb.fiscal_year_id == fy.id for fb in f.budgets)]
    return out
