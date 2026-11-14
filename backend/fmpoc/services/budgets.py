"""Budgets: hierarchy, system-managed Other, Budget 0, lifecycle, lock/unlock and derived values
(BR-016..027, BR-049/050, AC-BUD-*)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, Warning_, conflict, validation
from ..models import Budget, FiscalYear, TransactionAllocation, utcnow
from ..money import fmt, parse_amount
from .common import (active_allocation_totals, budget_display_code, budget_label, fy_brief, get_scoped,
                     quarters)

OTHER_CODE = "00"  # reserved child code for the system-managed Other child
BUDGET_ZERO_CODE = "0"


# ------------------------------------------------------------------ helpers
def snapshot(b: Budget) -> dict:
    return {
        "id": b.id, "fiscal_year_id": b.fiscal_year_id, "parent_budget_id": b.parent_budget_id,
        "parent_code": b.parent_code, "child_code": b.child_code, "name": b.name, "budget_type": b.budget_type,
        "amount": fmt(b.amount_cents), "requested_amount": fmt(b.requested_amount_cents), "status": b.status,
        "locked": b.locked, "system_managed": b.system_managed, "is_other": b.is_other,
        "is_budget_zero": b.is_budget_zero, "notes": b.notes, "status_reason": b.status_reason,
        "continues_budget_id": b.continues_budget_id,
        "continues_former_budget_id": b.continues_former_budget_id,  # 2.2.0 (#381)
        "invoiced_income": bool(b.invoiced_income),                  # 2.4.0 (#250)
    }


def children_of(db: Session, parent: Budget) -> tuple[list[Budget], Budget | None]:
    kids = list(db.scalars(select(Budget).where(Budget.parent_budget_id == parent.id, Budget.status != "DELETED")
                           .order_by(Budget.child_code)))
    other = next((k for k in kids if k.is_other), None)
    return [k for k in kids if not k.is_other], other


def family(db: Session, parent: Budget) -> list[Budget]:
    explicit, other = children_of(db, parent)
    return [parent, *explicit, *([other] if other else [])]


def top_of(db: Session, b: Budget) -> Budget:
    return db.get(Budget, b.parent_budget_id) if b.parent_budget_id else b


def recalc_other(db: Session, parent: Budget) -> Budget:
    """BR-017: Other = Parent Amount - SUM(explicit sub-budget amounts). Never user-authored."""
    explicit, other = children_of(db, parent)
    total = sum(c.amount_cents for c in explicit)
    if total > parent.amount_cents:
        raise AppError(422, "CHILDREN_EXCEED_PARENT",
                       "The sum of sub-budget amounts cannot exceed the parent budget amount.")
    if other is None:  # defensive: every parent always has Other (BR-016)
        other = Budget(workspace_id=parent.workspace_id, fiscal_year_id=parent.fiscal_year_id,
                       parent_budget_id=parent.id, parent_code=parent.parent_code, child_code=OTHER_CODE,
                       name="Other", budget_type=parent.budget_type, system_managed=True, is_other=True)
        db.add(other)
    other.amount_cents = parent.amount_cents - total
    other.status = parent.status
    other.locked = parent.locked
    other.invoiced_income = bool(parent.invoiced_income)       # 2.4.0 (#250): the family carries the flag
    db.flush()
    return other


def has_allocations(db: Session, budget_id: int) -> bool:
    return db.scalar(select(TransactionAllocation.id).where(TransactionAllocation.budget_id == budget_id).limit(1)) is not None


def state(b: Budget) -> dict:
    """BR-079/080 compact state indicator + accessible text."""
    if b.status == "DELETED":  # 1.7.3 (#52): only Auditors see deleted budgets
        return {"code": "DELETED", "icon": "X", "label": "Deleted", "tone": "grey"}
    if b.status == "REJECTED":
        return {"code": "REJECTED", "icon": "X", "label": "Rejected", "tone": "red"}
    if b.status == "INACTIVE":
        return {"code": "INACTIVE", "icon": "–", "label": "Inactive", "tone": "grey"}
    if b.status == "APPROVED":
        if b.locked:
            return {"code": "APPROVED_LOCKED", "icon": "lock-closed", "label": "Approved and locked", "tone": "green"}
        return {"code": "APPROVED_UNLOCKED", "icon": "lock-open", "label": "Approved and unlocked", "tone": "green"}
    return {"code": "DRAFT", "icon": "?", "label": "Draft (unapproved)", "tone": "yellow"}


def _fy_editable(fy: FiscalYear) -> None:
    if fy.status == "CLOSED":
        raise conflict("FISCAL_YEAR_CLOSED", "The Fiscal Year is closed; its budgets are immutable.")


def _editable(db: Session, b: Budget, fy: FiscalYear) -> None:
    _fy_editable(fy)
    if b.system_managed:
        raise AppError(422, "SYSTEM_MANAGED", "System-managed budgets (Other, Budget 0) cannot be edited.")
    if top_of(db, b).locked or b.locked:
        raise conflict("BUDGET_LOCKED", "The budget is locked. A Budget Manager must unlock it with a reason first.")


def create_budget_zero(db: Session, ctx, fy: FiscalYear) -> Budget:
    b0 = Budget(workspace_id=fy.workspace_id, fiscal_year_id=fy.id, parent_code=BUDGET_ZERO_CODE, child_code=None,
                name="Budget 0 (System)", budget_type="EXPENSE", amount_cents=0, status=fy.status if fy.status != "CLOSED" else "APPROVED",
                locked=fy.status != "DRAFT", system_managed=True, is_budget_zero=True,
                created_by_user_id=ctx.user.id if ctx.user else None)
    db.add(b0)
    db.flush()
    return b0


def budget_zero_for(db: Session, fy: FiscalYear) -> Budget:
    b0 = db.scalar(select(Budget).where(Budget.fiscal_year_id == fy.id, Budget.is_budget_zero.is_(True)))
    if b0 is None:
        raise AppError(500, "INTEGRITY", "Budget 0 missing for Fiscal Year.")
    return b0


# ------------------------------------------------------------------ mutations
def create(db: Session, ctx, data) -> Budget:
    fy = get_scoped(db, FiscalYear, data.fiscal_year_id, ctx, "Fiscal Year")
    _fy_editable(fy)
    try:
        amount = parse_amount(data.amount)
    except ValueError as e:
        raise validation(str(e), "amount") from None
    initial_status = "DRAFT" if fy.status == "DRAFT" else "APPROVED"  # amendments in an Approved FY start unlocked
    if data.parent_budget_id is None:
        if data.budget_type is None:
            raise validation("budget_type is required for a parent budget", "budget_type")
        if data.code == BUDGET_ZERO_CODE:
            raise validation("Code 0 is reserved for the protected Budget 0.", "code")
        dup = db.scalar(select(Budget.id).where(Budget.fiscal_year_id == fy.id, Budget.parent_budget_id.is_(None),
                                                 Budget.parent_code == data.code, Budget.status != "DELETED"))
        if dup:
            raise conflict("DUPLICATE_CODE", f"Budget code {data.code} already exists in {fy.display_name}.")
        b = Budget(workspace_id=ctx.workspace_id, fiscal_year_id=fy.id, parent_code=data.code, name=data.name,
                   budget_type=data.budget_type, amount_cents=amount, status=initial_status, locked=False,
                   notes=data.notes, created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id)
        db.add(b)
        db.flush()
        other = recalc_other(db, b)
        other.created_by_user_id = ctx.user.id
        _set_links(db, ctx, b, data, data.model_fields_set)
        audit.record(db, ctx, "BUDGET_CREATED", "budget", b.id, None, {**snapshot(b), "other": snapshot(other)})
        return b
    parent = get_scoped(db, Budget, data.parent_budget_id, ctx, "Parent budget")
    if parent.parent_budget_id is not None or parent.system_managed or parent.fiscal_year_id != fy.id:
        raise validation("Sub-budgets can only be added to a user parent budget in the same Fiscal Year.",
                         "parent_budget_id")
    if parent.status in ("REJECTED", "INACTIVE", "DELETED"):
        raise conflict("PARENT_NOT_ACTIVE", "Cannot add a sub-budget to a rejected, inactive or deleted budget.")
    if parent.locked:
        raise conflict("BUDGET_LOCKED", "The parent budget is locked.")
    if data.budget_type and data.budget_type != parent.budget_type:
        raise validation("A sub-budget must have the same type as its parent.", "budget_type")
    if data.code == OTHER_CODE:
        raise validation("Sub-budget code 00 is reserved for the system-managed Other.", "code")
    explicit, _ = children_of(db, parent)
    if any(c.child_code == data.code for c in explicit):
        raise conflict("DUPLICATE_CODE", f"Sub-budget {parent.parent_code}-{data.code} already exists.")
    before_parent = {**snapshot(parent), "other": snapshot(children_of(db, parent)[1])}
    b = Budget(workspace_id=ctx.workspace_id, fiscal_year_id=fy.id, parent_budget_id=parent.id,
               parent_code=parent.parent_code, child_code=data.code, name=data.name, budget_type=parent.budget_type,
               amount_cents=amount, status=parent.status, locked=False, notes=data.notes,
               invoiced_income=bool(parent.invoiced_income),      # 2.4.0 (#250): inherited
               created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id)
    db.add(b)
    db.flush()
    other = recalc_other(db, parent)  # raises CHILDREN_EXCEED_PARENT -> whole request rolls back (BR-018)
    _set_links(db, ctx, b, data, data.model_fields_set)
    audit.record(db, ctx, "BUDGET_CREATED", "budget", b.id, None,
                 {**snapshot(b), "parent_before": before_parent, "other_after": snapshot(other)})
    return b


def _not_deleted(b: Budget) -> None:
    if b.status == "DELETED":
        raise conflict("BUDGET_DELETED", "The budget has been deleted.")


def update(db: Session, ctx, b: Budget, data) -> Budget:
    fy = db.get(FiscalYear, b.fiscal_year_id)
    _not_deleted(b)
    _editable(db, b, fy)
    if b.status in ("REJECTED", "INACTIVE") and data.amount is not None:
        raise conflict("BUDGET_NOT_ACTIVE", "Rejected or inactive budgets have an allowed amount of zero.")
    parent = top_of(db, b)
    before = {**snapshot(b), "other": snapshot(children_of(db, parent)[1])}
    fields = data.model_fields_set
    if "name" in fields and data.name:
        b.name = data.name
    if "notes" in fields:
        b.notes = data.notes
    if "amount" in fields and data.amount is not None:
        try:
            b.amount_cents = parse_amount(data.amount)
        except ValueError as e:
            raise validation(str(e), "amount") from None
    _set_links(db, ctx, b, data, fields)  # 1.8.0 (#89) / 2.2.0 (#381): same rules as other edits
    b.updated_by_user_id = ctx.user.id
    db.flush()
    other = recalc_other(db, parent)
    audit.record(db, ctx, "BUDGET_UPDATED", "budget", b.id, before, {**snapshot(b), "other": snapshot(other)})
    return b


def _set_terminal(db: Session, ctx, b: Budget, status: str, reason: str, action: str) -> Budget:
    fy = db.get(FiscalYear, b.fiscal_year_id)
    _not_deleted(b)
    _editable(db, b, fy)
    if b.status not in ("DRAFT", "APPROVED"):
        raise conflict("INVALID_STATE", f"Budget is already {b.status.lower()}.")
    parent = top_of(db, b)
    targets = family(db, b) if b.parent_budget_id is None else [b]
    before = [snapshot(t) for t in targets]
    for t in targets:
        if t.is_other:
            continue
        t.requested_amount_cents = t.amount_cents
        t.amount_cents = 0  # BR-025: rejected budget has an allowed amount of zero
        t.status = status
        t.status_reason = reason
        t.updated_by_user_id = ctx.user.id
    db.flush()
    other = recalc_other(db, parent)
    if b.parent_budget_id is None:
        other.status = status
    audit.record(db, ctx, action, "budget", b.id, {"budgets": before},
                 {"budgets": [snapshot(t) for t in targets], "reason": reason, "other": snapshot(other)})
    return b


def reject(db: Session, ctx, b: Budget, reason: str) -> Budget:
    return _set_terminal(db, ctx, b, "REJECTED", reason, "BUDGET_REJECTED")


def inactivate(db: Session, ctx, b: Budget, reason: str) -> Budget:
    return _set_terminal(db, ctx, b, "INACTIVE", reason, "BUDGET_INACTIVATED")


# ------------------------------------------------------------------ 1.8.0 (#89) Historic Budget Traceability
def _continued_by(db: Session, target_id: int, except_id: int | None = None) -> Budget | None:
    q = select(Budget).where(Budget.continues_budget_id == target_id, Budget.status != "DELETED")
    if except_id is not None:
        q = q.where(Budget.id != except_id)
    return db.scalar(q.limit(1))


def continue_options(db: Session, ws_id: int, fy: FiscalYear, budget_type: str, sub_budget: bool,
                     budget_id: int | None = None) -> list[dict]:
    """Budgets a budget can continue: same type and level, from an earlier Fiscal Year, not Budget 0 / Other, not
    deleted, and not already continued by another budget (so each lineage offers its most recent budget, plus budgets
    that were never continued). Grouped by Fiscal Year (newest first), then Budget ID descending."""
    current = db.get(Budget, budget_id).continues_budget_id if budget_id else None
    fys = list(db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id, FiscalYear.start_date < fy.start_date)
                          .order_by(FiscalYear.start_date.desc())))
    taken = {r for r in db.scalars(select(Budget.continues_budget_id).where(
        Budget.workspace_id == ws_id, Budget.continues_budget_id.is_not(None), Budget.status != "DELETED",
        *([Budget.id != budget_id] if budget_id else [])))}
    groups = []
    for f in fys:
        q = select(Budget).where(Budget.fiscal_year_id == f.id, Budget.budget_type == budget_type,
                                 Budget.system_managed.is_(False), Budget.status != "DELETED")
        q = q.where(Budget.parent_budget_id.is_not(None) if sub_budget else Budget.parent_budget_id.is_(None))
        rows = []
        for b in db.scalars(q):
            if b.id in taken and b.id != current:
                continue
            parent = db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None
            code = budget_display_code(b, parent)
            rows.append({"id": b.id, "code": code, "name": b.name,
                         "label": f"{f.display_name} - {code} - {b.name}", "status": b.status})
        rows.sort(key=lambda r: [int(x) if x.isdigit() else x for x in r["code"].split("-")], reverse=True)
        if rows:
            groups.append({"fiscal_year": fy_brief(f), "options": rows})
    return groups


def _set_continues(db: Session, b: Budget, target_id: int | None) -> None:
    if target_id is None:
        b.continues_budget_id = None
        return
    if b.system_managed:
        raise validation("Budget 0 and the system-managed Other budgets are not linked.", "continues_budget_id")
    t = db.get(Budget, target_id)
    fy = db.get(FiscalYear, b.fiscal_year_id)
    tfy = db.get(FiscalYear, t.fiscal_year_id) if t is not None else None
    bad = (t is None or t.workspace_id != b.workspace_id or t.status == "DELETED" or t.system_managed
           or tfy.start_date >= fy.start_date)
    if bad:
        raise validation("Choose a budget of an earlier Fiscal Year.", "continues_budget_id")
    if t.budget_type != b.budget_type:
        raise validation("A budget can only continue a budget of the same type (Income or Expense).",
                         "continues_budget_id")
    if (t.parent_budget_id is None) != (b.parent_budget_id is None):
        raise validation("A budget continues a budget of the same level (budget to budget, sub-budget to sub-budget).",
                         "continues_budget_id")
    other = _continued_by(db, t.id, except_id=b.id)
    if other is not None:
        raise conflict("ALREADY_CONTINUED", "That budget is already continued by another budget.")
    b.continues_budget_id = t.id
    b.continues_former_budget_id = None  # 2.2.0 (#381): one predecessor - an earlier budget or a former budget


def _set_links(db: Session, ctx, b: Budget, data, fields) -> None:
    """1.8.0 (#89) continues_budget_id / 2.2.0 (#381) continues_former_budget_id from a create or update form: one
    predecessor, so choosing a former budget removes the link to an earlier budget and the other way round."""
    if "continues_former_budget_id" in fields and getattr(data, "continues_former_budget_id", None):
        b.continues_budget_id = None
        from . import budget_history as hist
        hist.set_link(db, ctx, b, data.continues_former_budget_id, record=False)
        return
    if "continues_budget_id" in fields:
        _set_continues(db, b, data.continues_budget_id)
    if "continues_former_budget_id" in fields and not data.continues_former_budget_id \
            and not getattr(data, "continues_budget_id", None):
        b.continues_former_budget_id = None


def lineage(db: Session, b: Budget) -> list[dict]:
    """The budget and every budget it is linked with, earlier and later, in Fiscal Year order."""
    chain, seen = [b], {b.id}
    cur = b
    while cur.continues_budget_id and cur.continues_budget_id not in seen:
        cur = db.get(Budget, cur.continues_budget_id)
        if cur is None:
            break
        chain.insert(0, cur)
        seen.add(cur.id)
    cur = b
    while True:
        nxt = _continued_by(db, cur.id)
        if nxt is None or nxt.id in seen:
            break
        chain.append(nxt)
        seen.add(nxt.id)
        cur = nxt
    totals = active_allocation_totals(db, [x.id for x in chain])
    out = []
    for x in chain:
        parent = db.get(Budget, x.parent_budget_id) if x.parent_budget_id else None
        if parent is None:  # a parent's actual is its own plus its sub-budgets' (as on the Budgets page)
            kids = [k.id for k in db.scalars(select(Budget).where(Budget.parent_budget_id == x.id))]
            actual = totals.get(x.id, 0) + sum(active_allocation_totals(db, kids).values()) if kids else totals.get(x.id, 0)
        else:
            actual = totals.get(x.id, 0)
        f = db.get(FiscalYear, x.fiscal_year_id)
        out.append({"id": x.id, "fiscal_year": fy_brief(f), "code": budget_display_code(x, parent), "name": x.name,
                    "amount": fmt(x.amount_cents), "actual": fmt(actual), "status": x.status, "this": x.id == b.id})
    return out


def delete(db: Session, ctx, b: Budget, reason: str) -> Budget:
    """1.7.3 (#52): a Budget Admin marks a budget of a not-yet-approved (Draft) Fiscal Year Deleted - BR-001 holds:
    nothing is removed from the database. Blocked while Register allocations, sub-budgets or a fundraiser use it."""
    from ..models import FundraiserBudget, RegisterTransaction
    fy = db.get(FiscalYear, b.fiscal_year_id)
    _not_deleted(b)
    if not reason or not reason.strip():
        raise validation("A reason for deleting the budget is required.", "reason")
    if b.system_managed:
        raise AppError(422, "SYSTEM_MANAGED", "Budget 0 and the system-managed Other budgets cannot be deleted.")
    if fy.status != "DRAFT":
        raise conflict("FISCAL_YEAR_APPROVED", f"Budgets can only be deleted while {fy.display_name} is not approved.")
    explicit, other = children_of(db, b) if b.parent_budget_id is None else ([], None)
    if explicit:
        raise conflict("HAS_SUB_BUDGETS", f"Delete its {len(explicit)} sub-budget(s) first.")
    targets = [b, *([other] if other is not None else [])]
    used = db.scalar(select(TransactionAllocation.id)
                     .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
                     .where(TransactionAllocation.budget_id.in_([t.id for t in targets]),
                            TransactionAllocation.removed_at.is_(None), RegisterTransaction.status != "DELETED")
                     .limit(1))
    if used is not None:
        raise conflict("HAS_ALLOCATIONS", "Register transactions are allocated to this budget. Move them to another "
                                          "budget first.")
    if db.scalar(select(FundraiserBudget.id).where(FundraiserBudget.budget_id.in_([t.id for t in targets])).limit(1)):
        raise conflict("USED_BY_FUNDRAISER", "A fundraiser uses this budget.")
    parent = top_of(db, b)
    before = [snapshot(t) for t in targets]
    for t in targets:
        t.status = "DELETED"
        t.status_reason = reason.strip()
        t.continues_budget_id = None  # 1.8.0 (#89): the earlier budget can be continued by another one again
        t.continues_former_budget_id = None  # 2.2.0 (#381): so can the budget from before PennyWarden
        t.updated_by_user_id = ctx.user.id
    db.flush()
    after = {"budgets": [snapshot(t) for t in targets], "reason": reason.strip()}
    if b.parent_budget_id is not None:
        after["other"] = snapshot(recalc_other(db, parent))  # the parent's Other gets the deleted amount back
    audit.record(db, ctx, "BUDGET_DELETED", "budget", b.id, {"budgets": before}, after)
    return b


def unlock(db: Session, ctx, b: Budget, reason: str) -> Budget:
    """BR-024: Budget Manager + reason + audit. Applies to the whole parent family."""
    fy = db.get(FiscalYear, b.fiscal_year_id)
    _fy_editable(fy)
    parent = top_of(db, b)
    if parent.is_budget_zero:
        raise AppError(422, "SYSTEM_MANAGED", "Budget 0 cannot be unlocked.")
    if fy.status != "APPROVED" or parent.status != "APPROVED" or not parent.locked:
        raise conflict("INVALID_STATE", "Only an Approved and locked budget can be unlocked.")
    if not reason or not reason.strip():
        raise validation("An unlock reason is required.", "reason")
    fam = family(db, parent)
    before = [snapshot(x) for x in fam]
    for x in fam:
        x.locked = False
        x.updated_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "BUDGET_UNLOCKED", "budget", parent.id, {"budgets": before},
                 {"budgets": [snapshot(x) for x in fam], "reason": reason})
    return parent


def set_invoiced_income(db: Session, ctx, b: Budget, on: bool) -> Budget:
    """2.4.0 (#250): mark an Income parent budget as Invoiced Income, or clear it. Budget Manager only (router);
    the whole family carries it (BR-016). An Approved budget must be unlocked first (with a reason, BR-023/024); a
    closed Fiscal Year refuses it (BR-012). Audited with before and after. It is a flag, not a budget type: the budget
    still counts as income everywhere. Its rules apply only with the Invoices module (later builds)."""
    fy = db.get(FiscalYear, b.fiscal_year_id)
    _fy_editable(fy)
    if b.parent_budget_id is not None or b.system_managed or b.is_budget_zero:
        raise validation("Invoiced Income is set on an Income parent budget; its sub-budgets and Other carry it.",
                         "invoiced_income")
    if b.budget_type != "INCOME":
        raise validation("Only an Income budget can be Invoiced Income.", "invoiced_income")
    if b.status in ("REJECTED", "INACTIVE", "DELETED"):
        raise conflict("INVALID_STATE", "A rejected, inactive or deleted budget can't be changed.")
    if b.locked:
        raise conflict("BUDGET_LOCKED", "The budget is locked. A Budget Manager must unlock it with a reason first.")
    if bool(b.invoiced_income) == on:
        return b
    fam = family(db, b)
    before = {"invoiced_income": bool(b.invoiced_income), "budget_ids": [x.id for x in fam]}
    for x in fam:
        x.invoiced_income = on
        x.updated_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "BUDGET_INVOICED_INCOME_SET" if on else "BUDGET_INVOICED_INCOME_CLEARED", "budget", b.id,
                 before, {"invoiced_income": on, "budget_ids": [x.id for x in fam]})
    return b


def lock(db: Session, ctx, b: Budget) -> Budget:
    fy = db.get(FiscalYear, b.fiscal_year_id)
    _fy_editable(fy)
    parent = top_of(db, b)
    if fy.status != "APPROVED" or parent.status != "APPROVED" or parent.locked:
        raise conflict("INVALID_STATE", "Only an Approved, unlocked budget in an Approved Fiscal Year can be locked.")
    recalc_other(db, parent)
    fam = family(db, parent)
    before = [snapshot(x) for x in fam]
    for x in fam:
        if x.status == "APPROVED":
            x.locked = True
            x.updated_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "BUDGET_LOCKED", "budget", parent.id, {"budgets": before},
                 {"budgets": [snapshot(x) for x in fam]})
    return parent


# ------------------------------------------------------------------ read models
def _row(b: Budget, parent: Budget | None, totals: dict, qtotals: list[dict], outside: dict) -> dict:
    actual = totals.get(b.id, 0)
    return {
        "id": b.id, "fiscal_year_id": b.fiscal_year_id, "parent_budget_id": b.parent_budget_id,
        "display_code": budget_display_code(b, parent), "label": budget_label(b, parent),
        "code": b.child_code if b.parent_budget_id else b.parent_code, "name": b.name, "budget_type": b.budget_type,
        "amount": fmt(b.amount_cents), "requested_amount": fmt(b.requested_amount_cents),
        "actual": fmt(actual), "remaining": fmt(b.amount_cents - actual),
        # v1.4 CR-019: income received above the budgeted amount is a surplus, not an overrun.
        "over_budget": actual > b.amount_cents and not b.is_budget_zero and b.budget_type != "INCOME",
        "above_budget": (fmt(actual - b.amount_cents) if b.budget_type == "INCOME" and not b.is_budget_zero
                         and actual > b.amount_cents else None),
        "quarters": [fmt(q.get(b.id, 0)) for q in qtotals], "outside_fiscal_year": fmt(outside.get(b.id, 0)),
        "continues_budget_id": b.continues_budget_id, "continues_former_budget_id": b.continues_former_budget_id,
        "status": b.status, "locked": b.locked, "state": state(b), "system_managed": b.system_managed,
        "invoiced_income": bool(b.invoiced_income),            # 2.4.0 (#250)
        "is_other": b.is_other, "is_budget_zero": b.is_budget_zero, "notes": b.notes,
        "status_reason": b.status_reason,
    }


def _sum_rows(rows: list[dict], key: str) -> int:
    from ..money import parse_amount as pa
    return sum(pa(r[key], allow_negative=True) for r in rows)


def tree(db: Session, fy: FiscalYear, include_hidden: bool = False, include_deleted: bool = False) -> dict:
    """Holistic Fiscal Year budget view: Income and Expense sections, Q1-Q4 + yearly actuals.
    include_deleted (1.7.3, #52): Auditors also see deleted budgets (never counted in the totals)."""
    q = select(Budget).where(Budget.fiscal_year_id == fy.id)
    if not include_deleted:
        q = q.where(Budget.status != "DELETED")
    budgets = list(db.scalars(q.order_by(Budget.parent_code, Budget.child_code)))
    ids = [b.id for b in budgets]
    totals = active_allocation_totals(db, ids)
    qs = quarters(fy)
    qtotals = [active_allocation_totals(db, ids, s, e) for _n, s, e in qs]
    outside = {bid: totals.get(bid, 0) - sum(q.get(bid, 0) for q in qtotals) for bid in ids}
    by_parent: dict[int, list[Budget]] = {}
    for b in budgets:
        if b.parent_budget_id:
            by_parent.setdefault(b.parent_budget_id, []).append(b)
    sections: dict[str, list] = {"INCOME": [], "EXPENSE": []}
    budget_zero = None
    for p in (b for b in budgets if b.parent_budget_id is None):
        if p.is_budget_zero:
            budget_zero = _row(p, None, totals, qtotals, outside)
            budget_zero.update(_budget_zero_flows(db, p.id))  # transfers post both directions to Budget 0
            continue
        kids = by_parent.get(p.id, [])
        explicit = [k for k in kids if not k.is_other]
        other = next((k for k in kids if k.is_other), None)
        # Parent roll-up actuals derive from child activity (AC-REG-011).
        p_tot = {p.id: sum(totals.get(k.id, 0) for k in kids) + totals.get(p.id, 0)}
        p_q = [{p.id: sum(q.get(k.id, 0) for k in kids)} for q in qtotals]
        p_out = {p.id: sum(outside.get(k.id, 0) for k in kids)}
        row = _row(p, None, p_tot, p_q, p_out)
        row["simple"] = not explicit
        row["selectable_budget_id"] = other.id if (not explicit and other) else None
        children = []
        for k in explicit:
            children.append(_row(k, p, totals, qtotals, outside))
        if explicit and other is not None:
            has_activity = totals.get(other.id, 0) != 0
            # BR-019: zero Other stays stored but hidden (still shown if it carries historical activity so roll-ups reconcile)
            if other.amount_cents > 0 or has_activity or include_hidden:
                orow = _row(other, p, totals, qtotals, outside)
                orow["hidden_zero_other"] = other.amount_cents == 0
                children.append(orow)
        row["children"] = children
        row["other_amount"] = fmt(other.amount_cents) if other else None
        sections[p.budget_type].append(row)

    def summary(rows, income: bool = False):
        rows = [r for r in rows if r["status"] != "DELETED"]
        active = [r for r in rows if r["status"] not in ("REJECTED", "INACTIVE")]
        remaining = _sum_rows(active, "amount") - _sum_rows(rows, "actual")
        return {"amount": fmt(_sum_rows(active, "amount")), "actual": fmt(_sum_rows(rows, "actual")),
                "remaining": fmt(remaining), "above_budget": fmt(-remaining) if income and remaining < 0 else None,
                "quarters": [fmt(sum(_amt(r["quarters"][i]) for r in rows)) for i in range(4)]}

    # 1.8.0 (#89): has_history - the budget continues an earlier one or is continued by a later one
    continued = set(db.scalars(select(Budget.continues_budget_id).where(
        Budget.continues_budget_id.in_(ids), Budget.status != "DELETED"))) if ids else set()
    for r in [*sections["INCOME"], *sections["EXPENSE"]]:
        for x in [r, *r["children"]]:
            x["has_history"] = bool(x.get("continues_budget_id") or x.get("continues_former_budget_id")) \
                or x["id"] in continued
    # 2.2.0 (#284): ... or years before PennyWarden are entered for its line
    from . import budget_history as hist
    if db.scalar(select(hist.BudgetHistoryEntry.id).where(hist.BudgetHistoryEntry.workspace_id == fy.workspace_id,
                                                          hist.BudgetHistoryEntry.retired_at.is_(None)).limit(1)):
        for r in [*sections["INCOME"], *sections["EXPENSE"]]:
            for x in [r, *r["children"]]:
                if not x["has_history"]:
                    b = db.get(Budget, x["id"])
                    x["has_history"] = b is not None and hist.has_entries(db, b)

    return {
        "fiscal_year": fy_brief(fy),
        "quarters": [{"name": n, "start_date": s.isoformat(), "end_date": e.isoformat()} for n, s, e in qs],
        "income": sections["INCOME"], "expense": sections["EXPENSE"],
        "income_summary": summary(sections["INCOME"], income=True), "expense_summary": summary(sections["EXPENSE"]),
        "budget_zero": budget_zero,
    }


def _budget_zero_flows(db: Session, budget_id: int) -> dict:
    from sqlalchemy import func
    from ..models import RegisterTransaction
    rows = db.execute(select(RegisterTransaction.transaction_type, func.coalesce(func.sum(TransactionAllocation.amount_cents), 0))
                      .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
                      .where(TransactionAllocation.budget_id == budget_id, TransactionAllocation.removed_at.is_(None),
                             RegisterTransaction.status == "ACTIVE")
                      .group_by(RegisterTransaction.transaction_type)).all()
    d = {k: int(v) for k, v in rows}
    return {"inflow": fmt(d.get("DEPOSIT", 0)), "outflow": fmt(d.get("WITHDRAWAL", 0))}


def _amt(s):
    from ..money import parse_amount as pa
    return pa(s, allow_negative=True)


def filter_options(db: Session, ws_id: int, fy: FiscalYear | None) -> list[dict]:
    """1.7.3 (#104): budgets for the Register's Budget filter - one Fiscal Year, or every year when fy is None.
    Label `<FY> - <Budget ID> - <Budget Name>`; order: Fiscal Year (newest first), Income before Expense, code.
    Budget 0 is left out. A parent stands for itself and its sub-budgets; a parent without explicit sub-budgets is
    listed once (its hidden Other budget is covered by it), an Other next to explicit sub-budgets is listed."""
    fys = [fy] if fy is not None else list(db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id)))
    fys.sort(key=lambda f: f.start_date, reverse=True)
    out = []
    for f in fys:
        budgets = list(db.scalars(select(Budget).where(Budget.fiscal_year_id == f.id, Budget.status != "DELETED")
                                  .order_by(Budget.parent_code, Budget.child_code)))
        for btype in ("INCOME", "EXPENSE"):
            for p in (b for b in budgets if b.parent_budget_id is None and b.budget_type == btype):
                if p.is_budget_zero:
                    continue
                out.append({"id": p.id, "fiscal_year_id": f.id, "budget_type": btype, "parent_budget_id": None,
                            "label": f"{f.display_name} - {budget_display_code(p, None)} - {p.name}"})
                kids = [k for k in budgets if k.parent_budget_id == p.id]
                if not any(not k.is_other for k in kids):
                    continue
                totals = active_allocation_totals(db, [k.id for k in kids if k.is_other])
                # as on the Budgets page: explicit sub-budgets, then Other unless it is zero and unused (BR-019)
                kids = [k for k in kids if not k.is_other] + [k for k in kids if k.is_other and (k.amount_cents > 0
                                                                                              or totals.get(k.id, 0))]
                for k in kids:
                    out.append({"id": k.id, "fiscal_year_id": f.id, "budget_type": btype, "parent_budget_id": p.id,
                                "label": f"{f.display_name} - {budget_display_code(k, p)} - {k.name}"})
    return out


def with_sub_budgets(db: Session, b: Budget) -> set[int]:
    """1.7.3 (#104): a parent budget stands for itself and its sub-budgets (the roll-up of the Budgets page)."""
    return {b.id, *db.scalars(select(Budget.id).where(Budget.parent_budget_id == b.id))}


def selectable(db: Session, ws_id: int, fy: FiscalYear, txn_type: str | None) -> list[dict]:
    """Leaf budgets eligible for new allocations (BR-019/020/025/050)."""
    if fy.status == "CLOSED":
        return []
    btype = {"DEPOSIT": "INCOME", "WITHDRAWAL": "EXPENSE"}.get(txn_type or "")
    budgets = list(db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id, Budget.status != "DELETED")
                              .order_by(Budget.parent_code, Budget.child_code)))
    totals = active_allocation_totals(db, [b.id for b in budgets])
    by_id = {b.id: b for b in budgets}
    out = []
    zero = None
    for p in (b for b in budgets if b.parent_budget_id is None):
        if p.is_budget_zero:
            zero = p
            continue
        if btype and p.budget_type != btype:
            continue
        if p.status in ("REJECTED", "INACTIVE"):
            continue
        kids = [b for b in budgets if b.parent_budget_id == p.id]
        explicit = [k for k in kids if not k.is_other and k.status not in ("REJECTED", "INACTIVE")]
        all_explicit = [k for k in kids if not k.is_other]
        other = next((k for k in kids if k.is_other), None)
        if not all_explicit and other is not None:
            out.append(_opt(other.id, p, None, fy, totals, p.amount_cents, label=budget_label(p, None)))
            continue
        for k in explicit:
            out.append(_opt(k.id, k, by_id[p.id], fy, totals, k.amount_cents))
        if other is not None and other.amount_cents > 0:
            out.append(_opt(other.id, other, p, fy, totals, other.amount_cents))
    if zero is not None:
        o = _opt(zero.id, zero, None, fy, totals, 0, label=f"0 {zero.name}")
        o["is_budget_zero"] = True
        o["warning"] = "Budget 0 is reserved for exceptional non-budget activity; selecting it requires confirmation."
        out.append(o)
    return out


def _opt(bid, b, parent, fy, totals, amount, label=None):
    actual = totals.get(bid, 0)
    return {"id": bid, "label": label or budget_label(b, parent), "budget_type": b.budget_type,
            "fiscal_year_id": fy.id, "fiscal_year_label": f"{fy.display_name} — {fy.status.title()}",
            "status": b.status, "amount": fmt(amount), "remaining": fmt(amount - actual), "is_budget_zero": False,
            "invoiced_income": bool(b.invoiced_income),
            "above_budget": fmt(actual - amount) if b.budget_type == "INCOME" and actual > amount else None}


def resolve_for_allocation(db: Session, ctx, budget_id: int, txn_type: str, unchanged: bool,
                           income_refund: bool = False) -> tuple[Budget, list[Warning_]]:
    """Validate a Budget chosen for an allocation and map a simple parent to its leaf Other. 2.4.0 (#254):
    `income_refund` = an invoice-overpayment refund withdrawal on an Invoiced Income budget (the BR-050 exception;
    only the invoice payment service sets it)."""
    b = get_scoped(db, Budget, budget_id, ctx, "Budget")
    warnings: list[Warning_] = []
    fy = db.get(FiscalYear, b.fiscal_year_id)
    if fy.status == "CLOSED":
        raise conflict("FISCAL_YEAR_CLOSED", f"{fy.display_name} is closed; no allocations may be added or changed.")
    if b.parent_budget_id is None and not b.is_budget_zero:
        explicit, other = children_of(db, b)
        if explicit:
            raise AppError(422, "ROLLUP_NOT_SELECTABLE",
                           "This budget has sub-budgets and is a roll-up; select a sub-budget instead.")
        b = other  # simple budget: backend keeps a leaf allocation on Other (BR-020)
    if b.is_budget_zero:
        if not unchanged:
            warnings.append(Warning_("BUDGET_ZERO", "Budget 0 is reserved for exceptional non-budget activity. "
                                                    "Confirm this is an approved exceptional use."))
        return b, warnings
    expected = {"DEPOSIT": "INCOME", "WITHDRAWAL": "EXPENSE"}[txn_type]
    if income_refund and txn_type == "WITHDRAWAL" and b.budget_type == "INCOME" and b.invoiced_income:
        expected = "INCOME"                     # 2.4.0 (#254): BR-050 as amended - invoice overpayment refunds only
    if b.budget_type != expected:
        raise AppError(422, "BUDGET_TYPE_MISMATCH",
                       f"{txn_type.title()} allocations may only reference {expected.title()} budgets.")
    if not unchanged:
        top = top_of(db, b)
        if b.status in ("REJECTED", "INACTIVE", "DELETED") or top.status in ("REJECTED", "INACTIVE", "DELETED"):
            raise conflict("BUDGET_NOT_ACTIVE", "New allocations to rejected or inactive budgets are not permitted.")
        if b.is_other and b.amount_cents == 0 and children_of(db, top)[0]:
            raise AppError(422, "OTHER_NOT_SELECTABLE", "The Other sub-budget has a zero amount and is not selectable.")
    return b, warnings
