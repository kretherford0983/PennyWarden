"""Register Transactions and Allocations (BR-042..072, AC-REG-*)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, Warning_, conflict, not_found, require_confirmations, validation
from ..models import (Attachment, BankAccount, Budget, Entity, FiscalYear, FiscalYearReview, RegisterTransaction,
                      TransactionAllocation, utcnow)
from ..money import fmt, parse_amount
from . import bank_accounts as bank
from . import budgets as bsvc
from . import checks
from .common import (budget_label, closest_fiscal_year, covering_fiscal_years, entity_brief, fy_brief, get_scoped)
from .entities import multiple_entity

BUDGET_TYPE_FOR = {"DEPOSIT": "INCOME", "WITHDRAWAL": "EXPENSE"}


# ------------------------------------------------------------------ snapshots / output
def alloc_snapshot(a: TransactionAllocation) -> dict:
    return {"id": a.id, "budget_id": a.budget_id, "entity_id": a.entity_id, "invoice_number": a.invoice_number,
            "invoice_date": a.invoice_date.isoformat() if a.invoice_date else None,
            "description": a.description, "amount": fmt(a.amount_cents), "notes": a.notes,
            "no_attachment": bool(a.no_attachment), "no_attachment_reason": a.no_attachment_reason,
            "removed": a.removed_at is not None}


def snapshot(t: RegisterTransaction) -> dict:
    return {"id": t.id, "bank_account_id": t.bank_account_id, "transaction_type": t.transaction_type,
            "transaction_date": t.transaction_date, "entry_timestamp": t.entry_timestamp, "clear_date": t.clear_date,
            "parent_entity_id": t.parent_entity_id, "check_number": t.check_number, "status": t.status,
            "notes": t.notes, "void_reason": t.void_reason, "delete_reason": t.delete_reason, "total": fmt(t.total_cents),
            "transfer_group": t.transfer_group, "no_attachment": bool(t.no_attachment),
            "no_attachment_reason": t.no_attachment_reason,
            "electronic_payment": bool(t.electronic_payment), "payment_method": t.payment_method,   # 2.1.0 (#260)
            "payment_method_other": t.payment_method_other, "payment_reference": t.payment_reference,
            "allocations": [alloc_snapshot(a) for a in t.live_allocations]}


# 2.1.0 (#260): electronic payments (withdrawals)
PAYMENT_METHOD_LABELS = {"ACH": "ACH / bill pay", "DEBIT_CARD": "Debit card", "WIRE": "Wire",
                         "ONLINE_PORTAL": "Online portal", "OTHER": "Other"}
ELECTRONIC_FIELDS = {"electronic_payment", "payment_method", "payment_method_other", "payment_reference"}


def payment_method_label(t: RegisterTransaction) -> str | None:
    if not t.electronic_payment:
        return None
    if t.payment_method == "OTHER" and t.payment_method_other:
        return t.payment_method_other
    return PAYMENT_METHOD_LABELS.get(t.payment_method or "", "Electronic")


def payment_text(t: RegisterTransaction) -> str | None:
    """What reports show where the check number would be: "Electronic (ACH / bill pay)", plus the number or
    reference when there is one; the check number for a check; None otherwise."""
    if t.electronic_payment:
        text = f"Electronic ({payment_method_label(t)})"
        if t.check_number:
            text += f", check #{t.check_number}"
        if t.payment_reference:
            text += f", ref. {t.payment_reference}"
        return text
    return t.check_number or None


def _reference_key(ref: str | None) -> str:
    return (ref or "").strip().lower()


def assert_reference_unused(db: Session, ws_id: int, account_id: int, ref: str | None,
                            exclude_id: int | None = None) -> None:
    """A payment reference is used once per bank account (case-insensitive), apart from check numbers."""
    key = _reference_key(ref)
    if not key:
        return
    q = select(RegisterTransaction).where(RegisterTransaction.workspace_id == ws_id,
                                          RegisterTransaction.bank_account_id == account_id,
                                          RegisterTransaction.payment_reference.is_not(None))
    for other in db.scalars(q):
        if other.id != exclude_id and _reference_key(other.payment_reference) == key:
            raise conflict("DUPLICATE_PAYMENT_REFERENCE",
                           f"Payment reference {ref} is already used in this account by transaction #{other.id}.")


def electronic_values(data, fields: set[str], t: RegisterTransaction | None, txn_type: str,
                      check_number: str | None) -> tuple[bool, str | None, str | None, str | None]:
    """The electronic-payment fields after this create/edit, validated (#260)."""
    cur = (bool(t.electronic_payment), t.payment_method, t.payment_method_other, t.payment_reference) if t \
        else (False, None, None, None)
    flag = bool(data.electronic_payment) if "electronic_payment" in fields and data.electronic_payment is not None \
        else cur[0]
    method = data.payment_method if "payment_method" in fields else cur[1]
    other = (data.payment_method_other or None) if "payment_method_other" in fields else cur[2]
    ref = (data.payment_reference or None) if "payment_reference" in fields else cur[3]
    if not flag:   # not (or no longer) electronic: the details go with it
        if any(k in fields and getattr(data, k, None) for k in ("payment_method", "payment_method_other",
                                                                "payment_reference")):
            raise validation("Payment method and reference apply to electronic payments only - tick "
                             "Electronic payment.", "electronic_payment")
        return False, None, None, None
    if txn_type != "WITHDRAWAL":
        raise validation("Electronic payment applies to Withdrawals only.", "electronic_payment")
    if not method:
        raise validation("Choose how it was paid (ACH / bill pay, debit card, wire, online portal or other).",
                         "payment_method")
    if method == "OTHER":
        other = (other or "").strip() or None
        if not other:
            raise validation("Describe the payment method (up to 60 characters).", "payment_method_other")
    else:
        other = None
    if ref and check_number:
        raise validation("Enter either a check number from your own check sequence or a payment reference, not "
                         "both.", "payment_reference")
    return True, method, other, ref



def _budget_info(db: Session, b: Budget) -> dict:
    parent = db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None
    label = budget_label(b, parent)
    if b.is_other and parent is not None:
        explicit, _ = bsvc.children_of(db, parent)
        if not explicit:
            label = budget_label(parent, None)  # simple budget shown as its parent (BR-020)
    fy = db.get(FiscalYear, b.fiscal_year_id)
    return {"id": b.id, "label": label, "budget_type": b.budget_type, "status": b.status,
            "is_budget_zero": b.is_budget_zero, "fiscal_year": fy_brief(fy)}


def out(db: Session, t: RegisterTransaction, running_balance: int | None = None) -> dict:
    reviews = {}
    ids = [a.id for a in t.allocations]
    if ids:
        for r in db.scalars(select(FiscalYearReview).where(FiscalYearReview.transaction_allocation_id.in_(ids))
                            .order_by(FiscalYearReview.id)):
            reviews.setdefault(r.transaction_allocation_id, []).append(review_out(db, r, brief=True))
    att_counts = {}
    check_printed = False
    for att in db.scalars(select(Attachment).where(
            (Attachment.transaction_id == t.id) | (Attachment.allocation_id.in_(ids or [-1])))):
        if att.system_generated and att.document_type == "CHECK_COPY":   # 2.0.0 (#161): a check record copy
            check_printed = True
        if att.active:
            key = ("t", t.id) if att.transaction_id else ("a", att.allocation_id)
            att_counts[key] = att_counts.get(key, 0) + 1
    acct = db.get(BankAccount, t.bank_account_id)
    allocs = []
    for a in t.live_allocations:
        allocs.append({**alloc_snapshot(a), "budget": _budget_info(db, a.budget), "entity": entity_brief(a.entity),
                       "reviews": reviews.get(a.id, []), "attachment_count": att_counts.get(("a", a.id), 0)})
    closed = is_closed_protected(db, t)
    total = t.total_cents
    return {
        **snapshot(t),
        "transaction_date": t.transaction_date.isoformat(), "entry_timestamp": t.entry_timestamp.isoformat() + "Z",
        "clear_date": t.clear_date.isoformat() if t.clear_date else None,
        "voided_at": t.voided_at.isoformat() + "Z" if t.voided_at else None,
        "deleted_at": t.deleted_at.isoformat() + "Z" if t.deleted_at else None,
        "bank_account": {"id": acct.id, "label": f"{acct.account_name} - {bank.masked(acct)}"},
        "entity": entity_brief(t.parent_entity), "allocations": allocs, "is_split": len(allocs) > 1,
        "deposit": fmt(total) if t.transaction_type == "DEPOSIT" else None,
        "withdrawal": fmt(total) if t.transaction_type == "WITHDRAWAL" else None,
        "running_balance": fmt(running_balance) if running_balance is not None else None,
        "cleared": t.clear_date is not None, "closed_fiscal_year_protected": closed,
        "zero_dollar_void": is_zero_dollar_void(t),
        "transfer": _transfer_info(db, t),
        "attachment_count": att_counts.get(("t", t.id), 0) + sum(v for k, v in att_counts.items() if k[0] == "a"),
        "has_pending_review": any(r["status"] == "PENDING" for rs in reviews.values() for r in rs),
        "invoice_numbers": sorted({a.invoice_number for a in t.live_allocations if a.invoice_number}),
        "check_printed": check_printed,
        "payment_method_label": payment_method_label(t),   # 2.1.0 (#260)
    }


def _transfer_info(db: Session, t: RegisterTransaction) -> dict | None:
    if not t.transfer_group:
        return None
    other = db.scalar(select(RegisterTransaction).where(RegisterTransaction.transfer_group == t.transfer_group,
                                                        RegisterTransaction.id != t.id))
    if other is None:
        return {"group": t.transfer_group, "counterpart_transaction_id": None, "counterpart_account": None}
    acct = db.get(BankAccount, other.bank_account_id)
    return {"group": t.transfer_group, "direction": "OUT" if t.transaction_type == "WITHDRAWAL" else "IN",
            "counterpart_transaction_id": other.id,
            "counterpart_account": {"id": acct.id, "label": f"{acct.account_name} - {bank.masked(acct)}"}}


def review_out(db: Session, r: FiscalYearReview, brief: bool = False) -> dict:
    d = {"id": r.id, "category": r.category, "status": r.status, "review_note": r.review_note,
         "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
         "reviewed_by_user_id": r.reviewed_by_user_id, "created_at": r.created_at.isoformat(),
         "transaction_allocation_id": r.transaction_allocation_id,
         "natural_fiscal_year": fy_brief(db.get(FiscalYear, r.natural_fiscal_year_id)) if r.natural_fiscal_year_id else None}
    if not brief:
        a = r.allocation
        t = a.transaction
        d.update({"transaction_id": t.id, "transaction_date": t.transaction_date.isoformat(),
                  "transaction_type": t.transaction_type, "transaction_status": t.status,
                  "amount": fmt(a.amount_cents), "budget": _budget_info(db, a.budget), "description": a.description,
                  "entity": entity_brief(a.entity or t.parent_entity)})
    return d


# ------------------------------------------------------------------ rules helpers
def is_closed_protected(db: Session, t: RegisterTransaction) -> bool:
    """BR-057: any live allocation referencing a Closed Fiscal Year makes financial fields immutable."""
    for a in t.live_allocations:
        fy = db.get(FiscalYear, a.budget.fiscal_year_id)
        if fy.status == "CLOSED":
            return True
    return False


def natural_fy_info(db: Session, ws_id: int, d: dt.date) -> dict:
    covering = covering_fiscal_years(db, ws_id, d)
    open_cov = [f for f in covering if f.status != "CLOSED"]
    closest = closest_fiscal_year(db, ws_id, d) if not covering else None
    return {"date": d.isoformat(), "covering": [fy_brief(f) for f in covering],
            "ambiguous": len(open_cov) > 1,
            "default_fiscal_year_id": open_cov[0].id if len(open_cov) == 1 else None,
            "closest": fy_brief(closest), "no_fiscal_year": not covering}


def _review_category(covering: list[FiscalYear], budget_fy_id: int) -> str | None:
    if not covering:
        return "NO_FISCAL_YEAR"
    if budget_fy_id not in {f.id for f in covering}:
        return "CROSS_FY"
    return None


@dataclass
class _Plan:
    data: object
    budget: Budget
    existing: TransactionAllocation | None
    amount: int
    entity_id: int | None
    category: str | None
    fy_or_date_changed: bool


def _entity(db: Session, ctx, entity_id: int | None, keep_ids: set[int]) -> Entity | None:
    if entity_id is None:
        return None
    e = db.get(Entity, entity_id)
    if e is None or e.workspace_id != ctx.workspace_id or e.is_system:
        raise validation("Entity not found.", "entity_id")
    if not e.active and e.id not in keep_ids:
        raise validation("Inactive Entities cannot be selected.", "entity_id")
    return e


def _plan_allocations(db: Session, ctx, *, txn_type: str, txn_date: dt.date, parent_entity_id: int | None,
                      allocs_in: list, existing: dict[int, TransactionAllocation], date_changed: bool,
                      keep_entity_ids: set[int], refund_ok: set[int] = frozenset(),
                      refund_alloc_ids: set[int] = frozenset()) -> tuple[list[_Plan], list[Warning_], int | None]:
    if not allocs_in:
        raise validation("At least one allocation is required.", "allocations")
    covering = covering_fiscal_years(db, ctx.workspace_id, txn_date)
    open_cov = [f for f in covering if f.status != "CLOSED"]
    warnings: list[Warning_] = []
    plans: list[_Plan] = []
    seen_ids = set()
    for i, ai in enumerate(allocs_in):
        ex = None
        if ai.id is not None:
            ex = existing.get(ai.id)
            if ex is None or ai.id in seen_ids:
                raise validation("Allocation does not belong to this transaction.", f"allocations.{i}.id")
            seen_ids.add(ai.id)
        try:
            amount = parse_amount(ai.amount, allow_zero=False)
        except ValueError as e:
            raise validation(str(e), f"allocations.{i}.amount") from None
        unchanged_budget = ex is not None and ex.budget_id == ai.budget_id
        # 2.4.0 (#254): a refund of an invoice overpayment (new, from the invoice; or an existing one left unchanged)
        refund = ai.budget_id in refund_ok or (ex is not None and ex.id in refund_alloc_ids and unchanged_budget)
        budget, bw = bsvc.resolve_for_allocation(db, ctx, ai.budget_id, txn_type, unchanged_budget, income_refund=refund)
        warnings.extend(bw)
        if ai.fiscal_year_id is not None and ai.fiscal_year_id != budget.fiscal_year_id:
            raise validation("The selected Budget does not belong to the selected Fiscal Year.",
                             f"allocations.{i}.fiscal_year_id")
        budget_changed = ex is None or ex.budget_id != budget.id
        if len(open_cov) > 1 and budget_changed and ai.fiscal_year_id is None:
            # BR-008: overlapping open Fiscal Years - never silently choose one.
            raise AppError(422, "AMBIGUOUS_FISCAL_YEAR",
                           "More than one open Fiscal Year covers the Transaction Date; explicitly select the "
                           "intended Fiscal Year for each allocation.",
                           candidates=[fy_brief(f) for f in open_cov])
        # entity rules
        if txn_type == "WITHDRAWAL":
            if ai.entity_id is not None and ai.entity_id != parent_entity_id:
                raise validation("Withdrawal allocations inherit the parent payee and cannot use a different Entity.",
                                 f"allocations.{i}.entity_id")
            entity_id = parent_entity_id
        else:
            if ai.invoice_number:
                raise validation("Invoice Number applies to Withdrawal allocations only.", f"allocations.{i}.invoice_number")
            if ai.invoice_date:
                raise validation("Invoice date applies to Withdrawal allocations only.", f"allocations.{i}.invoice_date")
            entity_id = ai.entity_id if ai.entity_id is not None else parent_entity_id
            _entity(db, ctx, entity_id, keep_entity_ids)
        category = None if budget.is_budget_zero else _review_category(covering, budget.fiscal_year_id)
        changed = budget_changed or date_changed
        if category and changed:
            bfy = db.get(FiscalYear, budget.fiscal_year_id)
            if category == "CROSS_FY":
                warnings.append(Warning_(
                    "CROSS_FY_ALLOCATION",
                    f"The selected budget belongs to {bfy.display_name}, which differs from the Fiscal Year covering "
                    f"the Transaction Date. The allocation will be flagged for Fiscal Year review.",
                    budget_fiscal_year=fy_brief(bfy), natural_fiscal_years=[fy_brief(f) for f in covering]))
            else:
                closest = closest_fiscal_year(db, ctx.workspace_id, txn_date)
                warnings.append(Warning_(
                    "NO_FISCAL_YEAR",
                    "No Fiscal Year covers the Transaction Date. The closest configured Fiscal Year is shown for "
                    "reference only and is not assumed to be correct; the allocation will be flagged for review.",
                    closest_fiscal_year=fy_brief(closest), budget_fiscal_year=fy_brief(bfy)))
        plans.append(_Plan(ai, budget, ex, amount, entity_id, category, changed))
    # de-duplicate warnings by code
    uniq = {}
    for w in warnings:
        uniq.setdefault(w.code, w)
    natural_id = covering[0].id if len(covering) == 1 else None
    return plans, list(uniq.values()), natural_id


def _deposit_parent_entity(db: Session, ws_id: int, plans: list[_Plan], parent_entity_id: int | None) -> int | None:
    ids = {p.entity_id for p in plans if p.entity_id is not None}
    if len(ids) > 1 or (len(plans) > 1 and ids and any(p.entity_id is None for p in plans)):
        return multiple_entity(db, ws_id).id  # BR-063: system Multiple at parent level
    if len(ids) == 1:
        return next(iter(ids))
    return parent_entity_id


def _account_for_register(db: Session, ctx, account_id: int) -> BankAccount:
    a = get_scoped(db, BankAccount, account_id, ctx, "Bank Account")
    if not a.register_enabled:
        raise validation("The Bank Account is not register-enabled.", "bank_account_id")
    if a.status != "ACTIVE":
        raise conflict("ACCOUNT_CLOSED", "The Bank Account is closed.")
    return a


def _apply_reviews(db: Session, ctx, alloc: TransactionAllocation, plan: _Plan, natural_id: int | None) -> None:
    pending = db.scalar(select(FiscalYearReview).where(FiscalYearReview.transaction_allocation_id == alloc.id,
                                                       FiscalYearReview.status == "PENDING"))
    if plan.category is None:
        if pending is not None:
            pending.status = "REASSIGNED"
            pending.reviewed_at = utcnow()
            pending.reviewed_by_user_id = ctx.user.id
            pending.review_note = "Resolved by reassignment/date change to the natural Fiscal Year."
        return
    if pending is not None:
        pending.category = plan.category
        pending.natural_fiscal_year_id = natural_id
        return
    if plan.fy_or_date_changed:
        db.add(FiscalYearReview(workspace_id=ctx.workspace_id, transaction_allocation_id=alloc.id,
                                category=plan.category, natural_fiscal_year_id=natural_id, status="PENDING"))


NO_ATTACHMENT_FIELDS = {"no_attachment", "no_attachment_reason"}
TRANSFER_EDITABLE_FIELDS = {"clear_date", "notes"} | NO_ATTACHMENT_FIELDS


def _allocations_financially_changed(plans: list, existing: dict) -> bool:
    """True when an allocation edit changes anything other than the documentation (no-attachment) markers."""
    kept = {p.existing.id for p in plans if p.existing is not None}
    if len(kept) != len(existing) or any(p.existing is None for p in plans):
        return True
    for p in plans:
        ex = p.existing
        if (ex.budget_id != p.budget.id or ex.amount_cents != p.amount or ex.entity_id != p.entity_id
                or (ex.invoice_number or None) != (p.data.invoice_number or None)
                or ex.invoice_date != p.data.invoice_date
                or (ex.description or None) != (p.data.description or None) or (ex.notes or None) != (p.data.notes or None)):
            return True
    return False


def _apply_no_attachment(t, ctx, flag: bool | None, reason: str | None) -> None:
    """v1.2: record that no supporting attachment will be provided (e.g. bank-initiated interest deposits)."""
    if flag is None:
        if t.no_attachment:
            t.no_attachment_reason = reason
        return
    if flag and not t.no_attachment:
        t.no_attachment_set_at, t.no_attachment_set_by_user_id = utcnow(), ctx.user.id
    t.no_attachment = bool(flag)
    t.no_attachment_reason = reason if flag else None
    if not flag:
        t.no_attachment_set_at = t.no_attachment_set_by_user_id = None


def check_clear_date(txn_date: dt.date, clear_date: dt.date | None) -> None:
    """1.7.2 (#56, BR-053): the bank cannot post a transaction before it was written."""
    if clear_date is not None and clear_date < txn_date:
        raise validation("The Clear/Post Date cannot be earlier than the Transaction Date.", "clear_date")


# ------------------------------------------------------------------ create
def create(db: Session, ctx, data, invoice_flow: dict | None = None) -> RegisterTransaction:
    """`invoice_flow` (2.4.0 #254, set only by the invoice payment service): {"refund_ok": budget ids} - lets a
    payment land on Invoiced Income budgets and a refund withdrawal use the BR-050 exception."""
    acct = _account_for_register(db, ctx, data.bank_account_id)
    txn_date = data.transaction_date or dt.date.today()  # BR-051 default
    check_clear_date(txn_date, data.clear_date)
    if data.check_number and data.transaction_type != "WITHDRAWAL":
        raise validation("Check Number applies to Withdrawals only.", "check_number")
    checks.assert_unused(db, ctx.workspace_id, acct.id, data.check_number)  # v1.3 CR-011 hard block
    epay = electronic_values(data, data.model_fields_set, None, data.transaction_type, data.check_number or None)
    if epay[0] and data.create_as_void:
        raise validation("A zero-dollar VOID record is not an electronic payment.", "electronic_payment")
    assert_reference_unused(db, ctx.workspace_id, acct.id, epay[3])
    parent_entity = _entity(db, ctx, data.entity_id, set())
    t = RegisterTransaction(workspace_id=ctx.workspace_id, bank_account_id=acct.id,
                            transaction_type=data.transaction_type, transaction_date=txn_date,
                            entry_timestamp=utcnow(), clear_date=data.clear_date,
                            parent_entity_id=parent_entity.id if parent_entity else None,
                            check_number=data.check_number or None, notes=data.notes, status="ACTIVE",
                            created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id)
    t.electronic_payment, t.payment_method, t.payment_method_other, t.payment_reference = epay
    if data.no_attachment:
        _apply_no_attachment(t, ctx, True, data.no_attachment_reason)
    if data.create_as_void:
        return _create_zero_void(db, ctx, t, data)
    if data.void_reason:
        raise validation("void_reason is only accepted when creating a zero-dollar VOID record.", "void_reason")
    plans, warnings, natural_id = _plan_allocations(
        db, ctx, txn_type=data.transaction_type, txn_date=txn_date, parent_entity_id=t.parent_entity_id,
        allocs_in=data.allocations, existing={}, date_changed=True, keep_entity_ids=set(),
        refund_ok=set((invoice_flow or {}).get("refund_ok") or ()))
    from . import invoice_payments as ipay                 # 2.4.0 (#254): Invoiced Income takes invoice payments only
    ipay.guard_new_plans(db, ctx, data.transaction_type, plans, invoice_flow is not None)
    if data.transaction_type == "DEPOSIT":
        t.parent_entity_id = _deposit_parent_entity(db, ctx.workspace_id, plans, t.parent_entity_id)
    dup = possible_duplicate(db, ctx.workspace_id, acct.id, txn_date, data.transaction_type,
                             sum(p.amount for p in plans), t.parent_entity_id)
    if dup is not None:
        warnings.insert(0, Warning_("POSSIBLE_DUPLICATE",
                                    f"Possible duplicate of transaction #{dup.id}: same account, date, type, amount "
                                    f"and entity. Save anyway?", transaction_id=dup.id))
    require_confirmations(warnings, data.confirmations)
    db.add(t)
    db.flush()
    for p in plans:
        a = TransactionAllocation(transaction_id=t.id, budget_id=p.budget.id, entity_id=p.entity_id,
                                  invoice_number=p.data.invoice_number or None, invoice_date=p.data.invoice_date,
                                  description=p.data.description,
                                  amount_cents=p.amount, notes=p.data.notes,
                                  created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id)
        if p.data.no_attachment:
            _apply_no_attachment(a, ctx, True, p.data.no_attachment_reason)
        db.add(a)
        db.flush()
        _apply_reviews(db, ctx, a, p, natural_id)
    db.flush()
    db.refresh(t)
    if t.total_cents <= 0:  # BR-072
        raise validation("An active transaction must have a total greater than zero.", "allocations")
    audit.record(db, ctx, "TRANSACTION_CREATED", "register_transaction", t.id, None,
                 {**snapshot(t), "confirmed_warnings": [w.code for w in warnings]})
    return t


def possible_duplicate(db: Session, ws_id: int, account_id: int, d: dt.date, txn_type: str, total: int,
                       entity_id: int | None) -> RegisterTransaction | None:
    """v1.3 CR-011: an ACTIVE transaction with the same account, date, type, amount and entity."""
    q = select(RegisterTransaction).where(RegisterTransaction.workspace_id == ws_id,
                                          RegisterTransaction.bank_account_id == account_id,
                                          RegisterTransaction.transaction_date == d,
                                          RegisterTransaction.transaction_type == txn_type,
                                          RegisterTransaction.status == "ACTIVE",
                                          RegisterTransaction.parent_entity_id.is_(None) if entity_id is None
                                          else RegisterTransaction.parent_entity_id == entity_id)
    return next((t for t in db.scalars(q.order_by(RegisterTransaction.id)) if t.total_cents == total), None)


def budget_zero_fiscal_year(db: Session, ctx, d: dt.date, fiscal_year_id: int | None) -> FiscalYear:
    """Fiscal Year whose protected Budget 0 carries a zero-dollar VOID record dated `d`."""
    if fiscal_year_id is not None:
        fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year")
    else:
        cov_all = covering_fiscal_years(db, ctx.workspace_id, d)
        cov = [f for f in cov_all if f.status != "CLOSED"]
        if cov_all and not cov:  # the date belongs to a Closed Fiscal Year: never re-home it silently
            raise conflict("FISCAL_YEAR_CLOSED", f"{cov_all[0].display_name} is closed.")
        if len(cov) > 1:
            raise AppError(422, "AMBIGUOUS_FISCAL_YEAR", "Select the Fiscal Year for this record.",
                           candidates=[fy_brief(f) for f in cov])
        fy = cov[0] if cov else None
        if fy is None:
            fy = min((f for f in db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ctx.workspace_id,
                                                                    FiscalYear.status != "CLOSED"))),
                     key=lambda f: abs((f.start_date - d).days), default=None)
        if fy is None:
            raise conflict("NO_OPEN_FISCAL_YEAR", "Create a Fiscal Year before recording transactions.")
    if fy.status == "CLOSED":
        raise conflict("FISCAL_YEAR_CLOSED", f"{fy.display_name} is closed.")
    return fy


def _create_zero_void(db: Session, ctx, t: RegisterTransaction, data) -> RegisterTransaction:
    """BR-072 / AC-REG-019: zero-dollar accountability record, created directly as VOID on Budget 0."""
    if not (data.void_reason or "").strip():
        raise validation("A Void Reason is required for a zero-dollar VOID record.", "void_reason")
    if data.allocations:
        raise validation("A zero-dollar VOID record has no user allocations; Budget 0 is used automatically.",
                         "allocations")
    fy = budget_zero_fiscal_year(db, ctx, t.transaction_date, data.fiscal_year_id)
    b0 = bsvc.budget_zero_for(db, fy)
    t.status = "VOID"
    t.void_reason = data.void_reason
    t.voided_at = utcnow()
    t.voided_by_user_id = ctx.user.id
    db.add(t)
    db.flush()
    db.add(TransactionAllocation(transaction_id=t.id, budget_id=b0.id, entity_id=t.parent_entity_id, amount_cents=0,
                                 description="Zero-dollar accountability record", created_by_user_id=ctx.user.id,
                                 updated_by_user_id=ctx.user.id))
    db.flush()
    db.refresh(t)
    audit.record(db, ctx, "TRANSACTION_CREATED_AS_VOID", "register_transaction", t.id, None, snapshot(t))
    return t


# ------------------------------------------------------------------ update
def update(db: Session, ctx, t: RegisterTransaction, data) -> RegisterTransaction:
    _not_deleted(t)
    if t.status == "VOID":
        raise conflict("TRANSACTION_VOID", "VOID transactions cannot be edited. Notes and attachments may be added.")
    if is_closed_protected(db, t):
        raise conflict("FISCAL_YEAR_CLOSED", "The transaction affects a Closed Fiscal Year and is immutable.")
    acct = db.get(BankAccount, t.bank_account_id)
    if acct.status != "ACTIVE":
        raise conflict("ACCOUNT_CLOSED", "The Bank Account is closed.")
    before = snapshot(t)
    f = data.model_fields_set - {"confirmations"}
    if t.transfer_group and f - TRANSFER_EDITABLE_FIELDS:
        raise conflict("TRANSFER_LOCKED", "Transfer transactions only allow Clear Date, Notes and the no-attachment "
                                          "flag to be edited. Void the transfer and enter it again to change it.")
    warnings: list[Warning_] = []
    new_type = data.transaction_type if "transaction_type" in f and data.transaction_type else t.transaction_type
    new_date = data.transaction_date if "transaction_date" in f and data.transaction_date else t.transaction_date
    new_entity_id = data.entity_id if "entity_id" in f else t.parent_entity_id
    if "entity_id" in f and new_type == "DEPOSIT" and new_entity_id is None and t.parent_entity_id:
        new_entity_id = None
    new_check = (data.check_number or None) if "check_number" in f else t.check_number
    new_clear = data.clear_date if "clear_date" in f else t.clear_date
    check_clear_date(new_date, new_clear)
    type_changed = new_type != t.transaction_type
    date_changed = new_date != t.transaction_date
    if type_changed:
        warnings.append(Warning_("TYPE_CHANGE", "Changing between Deposit and Withdrawal is a protected action. "
                                                "All allocations must be re-selected with compatible budgets."))
        if data.allocations is None:
            raise validation("Changing the transaction type requires re-selecting all allocations.", "allocations")
    if new_check and new_type != "WITHDRAWAL":
        raise validation("Check Number applies to Withdrawals only; clear it before changing to Deposit.", "check_number")
    if "check_number" in f and checks.check_key(new_check) != checks.check_key(t.check_number):
        checks.assert_unused(db, ctx.workspace_id, t.bank_account_id, new_check, exclude_id=t.id)
    # 2.1.0 (#260): electronic payment - validated against the new type and check number
    epay = electronic_values(data, f, t, new_type, new_check)
    if f & ELECTRONIC_FIELDS:
        if _reference_key(epay[3]) != _reference_key(t.payment_reference):
            assert_reference_unused(db, ctx.workspace_id, t.bank_account_id, epay[3], exclude_id=t.id)
        if epay[0] and not t.electronic_payment:
            from .checkprint import service as checkprint
            if t.check_number and checkprint.is_reprint(db, t):
                raise conflict("CHECK_PRINTED", f"Check #{t.check_number} was printed for this payment. If it was "
                                                "never sent, mark it spoiled first (Reprint check…), then mark the "
                                                "payment electronic.")
    keep_ids = {x for x in [t.parent_entity_id, *[a.entity_id for a in t.live_allocations]] if x}
    if "entity_id" in f and new_entity_id is not None:
        e = _entity(db, ctx, new_entity_id, keep_ids)
        if e and e.is_system:
            raise validation("Entity not found.", "entity_id")
    existing = {a.id: a for a in t.live_allocations}
    if data.allocations is not None:
        allocs_in = data.allocations
    elif date_changed or "entity_id" in f:
        from ..schemas import AllocationIn
        allocs_in = [AllocationIn(id=a.id, budget_id=a.budget_id, entity_id=(a.entity_id if t.transaction_type == "DEPOSIT" else None),
                                  invoice_number=a.invoice_number, invoice_date=a.invoice_date,
                                  description=a.description,
                                  amount=fmt(a.amount_cents), notes=a.notes, fiscal_year_id=a.budget.fiscal_year_id)
                     for a in t.live_allocations]
    else:
        allocs_in = None
    if allocs_in is not None and new_type == "DEPOSIT" and not type_changed and new_entity_id != t.parent_entity_id:
        # 2.1.2 (#344): the deposit's Entity changed - allocations still on the previous parent Entity follow the new
        # one (BR-063 derives the parent from the allocations, so a stale line Entity would silently put it back).
        allocs_in = [ai.model_copy(update={"entity_id": None})
                     if ai.entity_id is not None and ai.entity_id == t.parent_entity_id else ai for ai in allocs_in]
    parent_for_plan = new_entity_id
    if new_type == "WITHDRAWAL" and parent_for_plan is not None:
        pe = db.get(Entity, parent_for_plan)
        if pe is not None and pe.is_system:  # converting a split deposit: payee must be chosen explicitly
            raise validation("Select the payee Entity for the Withdrawal.", "entity_id")
    if new_type == "DEPOSIT" and parent_for_plan is not None:
        pe = db.get(Entity, parent_for_plan)
        if pe is not None and pe.is_system:
            parent_for_plan = None  # Multiple is derived, never an allocation default
    plans, natural_id = None, None
    from . import invoice_payments as ipay                 # 2.4.0 (#254)
    linked = ipay.linked_allocations(db, list(existing))
    if allocs_in is not None:
        plans, pw, natural_id = _plan_allocations(
            db, ctx, txn_type=new_type, txn_date=new_date, parent_entity_id=parent_for_plan, allocs_in=allocs_in,
            existing=existing, date_changed=date_changed, keep_entity_ids=keep_ids,
            refund_alloc_ids={aid for aid, k in linked.items() if k == "REFUND"})
        warnings.extend(pw)
        ipay.guard_edit(db, ctx, t, new_type, plans, existing, linked)
    fin_fields = f - NO_ATTACHMENT_FIELDS  # documentation flags are not financial edits
    if plans is not None and "allocations" in fin_fields and not _allocations_financially_changed(plans, existing):
        fin_fields = fin_fields - {"allocations"}
    if t.clear_date is not None and fin_fields:
        warnings.insert(0, Warning_("CLEARED_EDIT", "This transaction has cleared the bank. Editing a cleared "
                                                    "transaction is fully audited; confirm to continue."))
    # 2.1.2 (#344): confirmations are checked after the edit is applied, so a save that changes nothing needs no
    # confirmation and writes no audit entry (the request is only committed when update() returns).
    # ---- apply
    t.transaction_type, t.transaction_date, t.clear_date, t.check_number = new_type, new_date, new_clear, new_check
    t.electronic_payment, t.payment_method, t.payment_method_other, t.payment_reference = epay
    if "notes" in f:
        t.notes = data.notes
    if f & NO_ATTACHMENT_FIELDS:
        _apply_no_attachment(t, ctx, data.no_attachment if "no_attachment" in f else None, data.no_attachment_reason)
    t.parent_entity_id = new_entity_id
    if plans is not None:
        kept = set()
        for p in plans:
            if p.existing is not None:
                a = p.existing
                kept.add(a.id)
            else:
                a = TransactionAllocation(transaction_id=t.id, created_by_user_id=ctx.user.id)
                db.add(a)
            a.budget_id, a.entity_id, a.amount_cents = p.budget.id, p.entity_id, p.amount
            a.invoice_number = p.data.invoice_number or None
            a.invoice_date = p.data.invoice_date
            a.description, a.notes = p.data.description, p.data.notes
            if "no_attachment" in p.data.model_fields_set or "no_attachment_reason" in p.data.model_fields_set:
                _apply_no_attachment(a, ctx, p.data.no_attachment if "no_attachment" in p.data.model_fields_set else None,
                                     p.data.no_attachment_reason)
            a.updated_by_user_id = ctx.user.id
            db.flush()
            db.expire(a, ["entity", "budget"])  # 2.1.2 (#344): the response showed the line's previous Entity
            _apply_reviews(db, ctx, a, p, natural_id)
        removed = [aid for aid in existing if aid not in kept]
        if removed:                      # 2.2.0 (#325): Donations page lines on removed lines await a deposit again
            from . import donations
            donations.unlink_for_deposit(db, ctx, t, removed)
        for aid, a in existing.items():
            if aid not in kept:
                a.removed_at = utcnow()  # retained for history, never hard deleted
                a.updated_by_user_id = ctx.user.id
                for r in db.scalars(select(FiscalYearReview).where(FiscalYearReview.transaction_allocation_id == aid,
                                                                   FiscalYearReview.status == "PENDING")):
                    r.status, r.reviewed_at, r.reviewed_by_user_id = "REASSIGNED", utcnow(), ctx.user.id
                    r.review_note = "Allocation removed from the transaction during edit."
        if new_type == "DEPOSIT":
            t.parent_entity_id = _deposit_parent_entity(db, ctx.workspace_id, plans, new_entity_id)
    t.updated_by_user_id = ctx.user.id
    db.flush()
    db.expire(t, ["allocations"])
    db.refresh(t)
    if t.total_cents <= 0:
        raise validation("An active transaction must have a total greater than zero.", "allocations")
    if snapshot(t) == before:
        db.rollback()  # nothing changed: drop the updated-by stamp, no confirmation, no audit entry
        return db.get(RegisterTransaction, before["id"])
    require_confirmations(warnings, data.confirmations)
    audit.record(db, ctx, "TRANSACTION_UPDATED", "register_transaction", t.id, before,
                 {**snapshot(t), "confirmed_warnings": [w.code for w in warnings]})
    return t


def void(db: Session, ctx, t: RegisterTransaction, reason: str, confirm: bool) -> RegisterTransaction:
    """BR-066..071. Voiding one leg of a transfer voids both legs together (v1.2)."""
    from .transfers import legs as transfer_legs
    group = transfer_legs(db, t)
    for leg in group:
        _not_deleted(leg)
        if leg.status == "VOID":
            raise conflict("TRANSACTION_VOID", "The transaction is already VOID; voiding is irreversible.")
        if is_closed_protected(db, leg):
            raise conflict("FISCAL_YEAR_CLOSED", "A transaction affecting a Closed Fiscal Year cannot be voided.")
        if db.get(BankAccount, leg.bank_account_id).status != "ACTIVE":
            raise conflict("ACCOUNT_CLOSED", "The Bank Account is closed.")
    if not (reason or "").strip():
        raise validation("A Void Reason is required.", "reason")
    if not confirm:
        raise AppError(409, "CONFIRMATION_REQUIRED", "Voiding is irreversible and requires confirmation.",
                       warnings=[{"code": "IRREVERSIBLE", "message": "Void cannot be reversed.", "details": {}}])
    for leg in group:
        before = snapshot(leg)
        leg.status = "VOID"
        leg.void_reason = reason
        leg.voided_at = utcnow()
        leg.voided_by_user_id = ctx.user.id
        leg.updated_by_user_id = ctx.user.id
        db.flush()
        audit.record(db, ctx, "TRANSACTION_VOIDED", "register_transaction", leg.id, before,
                     {**snapshot(leg), "voided_with_transfer_leg": [x.id for x in group if x.id != leg.id] or None})
        if leg.transaction_type == "DEPOSIT":       # 2.2.0 (#325): Donations page lines await a deposit again
            from . import donations
            donations.unlink_for_deposit(db, ctx, leg)
        from . import invoice_payments as ipay      # 2.4.0 (#254): a linked invoice re-opens (same transaction)
        ipay.after_transaction_change(db, ctx, leg)
    return t


def _not_deleted(t: RegisterTransaction) -> None:
    if t.status == "DELETED":
        raise conflict("TRANSACTION_DELETED", "The transaction has been deleted.")


def delete(db: Session, ctx, t: RegisterTransaction, reason: str) -> RegisterTransaction:
    """1.7.3 (#53): a Register Admin marks an ACTIVE, uncleared transaction Deleted instead of voiding it (BR-001: it
    stays in the database for Auditors and the audit trail). A Clear/Post Date means it has posted at the bank and is
    final - remove the clear date first if it was put on the wrong line. Deleting a transfer leg deletes both legs.
    2.1.0 (#289): its check number is released (refused while a printed check carries it)."""
    from .transfers import legs as transfer_legs
    if not (reason or "").strip():
        raise validation("A reason for deleting the transaction is required.", "reason")
    group = transfer_legs(db, t)
    for leg in group:
        _not_deleted(leg)
        if leg.status != "ACTIVE":
            raise conflict("TRANSACTION_VOID", "VOID records cannot be deleted.")
        if leg.clear_date is not None:
            raise conflict("TRANSACTION_CLEARED", "A cleared transaction has posted at the bank and cannot be deleted. "
                                                  "If the clear date is on the wrong transaction, remove it first.")
        if is_closed_protected(db, leg):
            raise conflict("FISCAL_YEAR_CLOSED", "A transaction affecting a Closed Fiscal Year cannot be deleted.")
        if db.get(BankAccount, leg.bank_account_id).status != "ACTIVE":
            raise conflict("ACCOUNT_CLOSED", "The Bank Account is closed.")
        # 2.1.0 (#289): deleting releases the check number - not while a printed (not spoiled) check carries it
        if leg.check_number:
            from .checkprint import service as checkprint
            if checkprint.is_reprint(db, leg):
                raise conflict("CHECK_PRINTED", f"Check #{leg.check_number} was printed for this transaction, so a "
                                                "paper check exists. Void the transaction instead, or mark the check "
                                                "spoiled first (Reprint check…), then delete it.")
    for leg in group:
        before = snapshot(leg)
        leg.status = "DELETED"
        leg.delete_reason = reason.strip()
        leg.deleted_at = utcnow()
        leg.deleted_by_user_id = ctx.user.id
        leg.updated_by_user_id = ctx.user.id
        db.flush()
        audit.record(db, ctx, "TRANSACTION_DELETED", "register_transaction", leg.id, before,
                     {**snapshot(leg), "deleted_with_transfer_leg": [x.id for x in group if x.id != leg.id] or None})
        if leg.transaction_type == "DEPOSIT":       # 2.2.0 (#325)
            from . import donations
            donations.unlink_for_deposit(db, ctx, leg)
        from . import invoice_payments as ipay      # 2.4.0 (#254): a linked invoice re-opens
        ipay.after_transaction_change(db, ctx, leg)
    return t


def is_zero_dollar_void(t: RegisterTransaction) -> bool:
    live = t.live_allocations
    return t.status == "VOID" and t.total_cents == 0 and bool(live) and all(a.budget.is_budget_zero for a in live)


def correct_void_date(db: Session, ctx, t: RegisterTransaction, new_date: dt.date, fiscal_year_id: int | None,
                      reason: str | None) -> RegisterTransaction:
    """Change request CR-001: the Transaction Date of a VOID transaction may be corrected.

    Only the date changes; amounts, allocations' figures, void reason and attachments are untouched and VOID
    transactions keep zero balance/budget impact. For a zero-dollar VOID accountability record the protected
    Budget 0 allocation follows the corrected date (same automatic Fiscal Year selection as at creation).
    Closed-Fiscal-Year protection (BR-057/071) still applies to the current and the target Fiscal Year.
    """
    if t.status != "VOID":
        raise conflict("NOT_VOID", "Date correction applies to VOID transactions only; edit active transactions normally.")
    if is_closed_protected(db, t):
        raise conflict("FISCAL_YEAR_CLOSED", "The transaction affects a Closed Fiscal Year and is immutable.")
    before = snapshot(t)
    moved_to = None
    if is_zero_dollar_void(t):
        fy = budget_zero_fiscal_year(db, ctx, new_date, fiscal_year_id)
        b0 = bsvc.budget_zero_for(db, fy)
        for a in t.live_allocations:
            if a.budget_id != b0.id:
                a.budget = b0  # sets budget_id and keeps the relationship current
                a.updated_by_user_id = ctx.user.id
                moved_to = fy.display_name
    elif fiscal_year_id is not None:
        raise validation("fiscal_year_id applies only to zero-dollar VOID records.", "fiscal_year_id")
    if new_date == t.transaction_date and moved_to is None:
        raise conflict("NO_CHANGE", "The Transaction Date is unchanged.")
    check_clear_date(new_date, t.clear_date)
    t.transaction_date = new_date
    t.updated_by_user_id = ctx.user.id
    db.flush()
    db.expire(t, ["allocations"])
    db.refresh(t)
    audit.record(db, ctx, "TRANSACTION_VOID_DATE_CORRECTED", "register_transaction", t.id, before,
                 {**snapshot(t), "reason": reason, "budget_zero_fiscal_year": moved_to})
    return t


def correct_void_check_number(db: Session, ctx, t: RegisterTransaction, number: str | None,
                              reason: str) -> RegisterTransaction:
    """v1.3 CR-011: clear or change the check number of a VOID record (e.g. voided because the wrong number was
    entered), releasing the old number. A new number must not be used by any other record in the account. Only the
    check number changes; a stamped note records the correction on the record itself. Closed Fiscal Years stay
    immutable."""
    if t.status != "VOID":
        raise conflict("NOT_VOID", "Check number correction here applies to VOID records; edit active transactions normally.")
    if is_closed_protected(db, t):
        raise conflict("FISCAL_YEAR_CLOSED", "The transaction affects a Closed Fiscal Year and is immutable.")
    number = (number or "").strip() or None
    if number and t.transaction_type != "WITHDRAWAL":
        raise validation("Check Number applies to Withdrawals only.", "check_number")
    if checks.check_key(number) == checks.check_key(t.check_number) and number == t.check_number:
        raise conflict("NO_CHANGE", "The check number is unchanged.")
    if checks.check_key(number) != checks.check_key(t.check_number):
        checks.assert_unused(db, ctx.workspace_id, t.bank_account_id, number, exclude_id=t.id)
    before = snapshot(t)
    old = t.check_number
    t.check_number = number
    stamp = (f"[{utcnow().strftime('%Y-%m-%d %H:%M')} UTC {ctx.user.username}] Check number corrected from "
             f"{old or '(none)'} to {number or '(none)'}: {reason}")
    t.notes = f"{t.notes}\n{stamp}" if t.notes else stamp
    t.updated_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "TRANSACTION_VOID_CHECK_NUMBER_CORRECTED", "register_transaction", t.id, before,
                 {**snapshot(t), "old_check_number": old, "new_check_number": number, "reason": reason})
    return t


def add_note(db: Session, ctx, t: RegisterTransaction, note: str) -> RegisterTransaction:
    """Append-only supporting note; allowed after VOID and on closed-year transactions (non-financial)."""
    before = {"notes": t.notes}
    stamp = f"[{utcnow().strftime('%Y-%m-%d %H:%M')} UTC {ctx.user.username}] {note}"
    t.notes = f"{t.notes}\n{stamp}" if t.notes else stamp
    db.flush()
    audit.record(db, ctx, "TRANSACTION_NOTE_ADDED", "register_transaction", t.id, before, {"notes": t.notes})
    return t


def resolve_review(db: Session, ctx, r: FiscalYearReview, note: str | None) -> FiscalYearReview:
    if r.status != "PENDING":
        raise conflict("INVALID_STATE", "The review item is already resolved.")
    a = r.allocation
    if a.removed_at is not None:
        raise conflict("INVALID_STATE", "The allocation was removed.")
    fy = db.get(FiscalYear, a.budget.fiscal_year_id)
    if fy.status == "CLOSED":
        raise conflict("FISCAL_YEAR_CLOSED", "The budget Fiscal Year is closed.")
    before = {"id": r.id, "status": r.status, "category": r.category}
    r.status = "REVIEWED"
    r.review_note = note
    r.reviewed_at = utcnow()
    r.reviewed_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "FISCAL_YEAR_REVIEW_CONFIRMED", "fiscal_year_review", r.id, before,
                 {"id": r.id, "status": r.status, "category": r.category, "review_note": note,
                  "transaction_allocation_id": a.id})
    return r


# ------------------------------------------------------------------ register view
SORT_FIELDS = {"transaction_date", "entry_timestamp", "amount", "check_number", "clear_date"}
# 2.1.0 (#262): the register opens sorted the way each user left it (app_user.register_sort); this is the default
DEFAULT_REGISTER_SORT = "transaction_date:asc"


def register_view(db: Session, ctx, acct: BankAccount, *, fiscal_year: FiscalYear | None, txn_type: str | None,
                  status: str | None, date_from: dt.date | None, date_to: dt.date | None, search: str | None,
                  sort: str, direction: str, attachments: str | None = None, budget: Budget | None = None,
                  include_deleted: bool = False, payment: str | None = None) -> dict:
    """attachments (1.6.7; 2.1.0, #258):
      "yes"     - the transactions with an attachment, counted exactly like the paperclip in the row (the
                  transaction's own attachments plus those of its allocations);
      "missing" - exactly what the Fiscal Year documentation review warns about (services/documentation.classify):
                  no documentation, or a "no attachment will be provided" mark without a reason; ACTIVE only.
                  "no" (1.6.7) is accepted as the same thing, so old links keep working;
      "marked"  - every transaction with a "no attachment will be provided" mark (transaction or allocation), with or
                  without a reason (without one it is also under "missing")."""
    txns = list(db.scalars(select(RegisterTransaction).where(RegisterTransaction.bank_account_id == acct.id)
                           .order_by(RegisterTransaction.transaction_date, RegisterTransaction.entry_timestamp,
                                     RegisterTransaction.id)))
    running = acct.opening_balance_cents or 0
    rb: dict[int, int] = {}
    for t in txns:  # continuous register across the account lifetime (BR-042)
        if t.status == "ACTIVE":
            running += t.total_cents if t.transaction_type == "DEPOSIT" else -t.total_cents
        rb[t.id] = running
    lo, hi = date_from, date_to
    if fiscal_year is not None:
        lo = max(lo, fiscal_year.start_date) if lo else fiscal_year.start_date
        hi = min(hi, fiscal_year.end_date) if hi else fiscal_year.end_date
    starting = None
    if lo is not None:  # BR-043: Available Balance at the end of the day before the period start (1.7.2, #56)
        starting = bank.available_cents(db, acct, lo - dt.timedelta(days=1))
    rows = []
    needle = (search or "").strip().lower()
    # 1.7.3 (#104): Budget filter - the transactions with a (live) allocation to the budget or its sub-budgets, and
    # that budget's share of each one
    bids = bsvc.with_sub_budgets(db, budget) if budget is not None else None
    share: dict[int, int] = {}
    for t in txns:
        # 1.7.3 (#53): deleted transactions are only listed for Auditors, with the "Deleted" status filter
        if t.status == "DELETED" and not (include_deleted and status == "deleted"):
            continue
        if status == "deleted" and t.status != "DELETED":
            continue
        if lo and t.transaction_date < lo or hi and t.transaction_date > hi:
            continue
        if txn_type and t.transaction_type != txn_type:
            continue
        if status == "cleared" and (t.status != "ACTIVE" or t.clear_date is None):
            continue
        if status == "uncleared" and (t.status != "ACTIVE" or t.clear_date is not None):
            continue
        if status == "void" and t.status != "VOID":
            continue
        if status == "active" and t.status != "ACTIVE":
            continue
        # 2.1.0 (#260): Payment method filter - check / electronic / none (withdrawals only)
        if payment == "electronic" and not t.electronic_payment:
            continue
        if payment == "check" and (t.transaction_type != "WITHDRAWAL" or t.electronic_payment or not t.check_number):
            continue
        if payment == "none" and (t.transaction_type != "WITHDRAWAL" or t.electronic_payment or t.check_number):
            continue
        if bids is not None:
            part = [a.amount_cents for a in t.live_allocations if a.budget_id in bids]
            if not part:
                continue
            share[t.id] = sum(part)
        if needle:
            hay = [t.check_number or "", t.payment_reference or "", t.notes or "", fmt(t.total_cents) or "",
                   t.parent_entity.display_name if t.parent_entity else ""]
            for a in t.live_allocations:
                hay += [a.description or "", a.invoice_number or "", a.entity.display_name if a.entity else ""]
            if not any(needle in h.lower() for h in hay):
                continue
        rows.append(t)
    # 2.1.0 (#262): rows with the same date keep the order they were entered (entry timestamp, then id). An uncleared
    # transaction counts as "not yet cleared": after every cleared one ascending, first descending, by its Date.
    keyf = {
        "transaction_date": lambda t: (t.transaction_date, t.entry_timestamp, t.id),
        "entry_timestamp": lambda t: (t.entry_timestamp, t.id),
        "amount": lambda t: (t.total_cents, t.id),
        "check_number": lambda t: (t.check_number or "", t.id),
        "clear_date": lambda t: (t.clear_date is None, t.clear_date or dt.date.max, t.transaction_date,
                                 t.entry_timestamp, t.id),
    }[sort]
    rows.sort(key=keyf)
    if direction == "desc":   # reverse the whole order, so ties also read newest-entered first
        rows.reverse()
    if sort == "clear_date":
        # 2.1.0 (#262): sorted by Cleared, the running balance is the bank (cleared) balance after each cleared item,
        # in clear order - blank on uncleared rows. Same continuous register (BR-042), cleared items only.
        cleared = sorted((t for t in txns if t.status == "ACTIVE" and t.clear_date is not None),
                         key=lambda t: (t.clear_date, t.transaction_date, t.entry_timestamp, t.id))
        bank_running = acct.opening_balance_cents or 0
        crb: dict[int, int] = {}
        for t in cleared:
            bank_running += t.total_cents if t.transaction_type == "DEPOSIT" else -t.total_cents
            crb[t.id] = bank_running
        shown = [out(db, t, crb.get(t.id)) for t in rows]
    else:
        shown = [out(db, t, rb[t.id]) for t in rows]
    if bids is not None:
        for x in shown:
            x["budget_share"] = fmt(share[x["id"]])
    from .documentation import categories, is_marked
    doc = categories(db, rows)
    by_id = {t.id: t for t in rows}
    for x in shown:   # 2.1.0 (#258): why a row is under "Missing" (None when the review has nothing to say)
        x["documentation"] = doc.get(x["id"])
    if attachments == "yes":
        shown = [x for x in shown if x["attachment_count"] > 0]
    elif attachments in ("missing", "no"):
        shown = [x for x in shown if x["documentation"] is not None]
    elif attachments == "marked":
        shown = [x for x in shown if is_marked(by_id[x["id"]])]
    return {
        "bank_account": bank.out(db, acct),
        "fiscal_year": fy_brief(fiscal_year),
        "date_from": lo.isoformat() if lo else None, "date_to": hi.isoformat() if hi else None,
        "starting_balance": fmt(starting) if starting is not None else fmt(acct.opening_balance_cents or 0),
        "ending_balance": fmt(bank.available_cents(db, acct, hi) if hi else bank.available_cents(db, acct)),
        # 1.7.2 (#56/#57): Current = the bank balance (cleared only); Available = everything written or deposited
        "current_balance": fmt(bank.current_cents(db, acct)),
        "available_balance": fmt(bank.available_cents(db, acct)),
        # the bank balance and the outstanding items behind the starting and ending balances (a bank reconciliation)
        "opening_reconciliation": reconciliation(db, acct, lo - dt.timedelta(days=1)) if lo is not None else None,
        "ending_reconciliation": reconciliation(db, acct, hi) if hi is not None else None,
        "transactions": shown,
        "sort": sort, "direction": direction,
        # 2.1.0 (#262): what the running-balance column shows for this sort
        "running_balance_kind": "cleared" if sort == "clear_date" else "register",
        "budget": _budget_brief(db, budget) if budget is not None else None,
    }


def _budget_brief(db: Session, b: Budget) -> dict:
    parent = db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None
    return {"id": b.id, "label": budget_label(b, parent), "fiscal_year_id": b.fiscal_year_id}


def reconciliation(db: Session, acct: BankAccount, as_of: dt.date) -> dict:
    """1.7.2 (#56): bank balance on a date + outstanding items = Available Balance on that date."""
    items = []
    for t in bank.outstanding(db, acct, as_of):
        cents = sum(a.amount_cents for a in t.live_allocations)
        items.append({"id": t.id, "transaction_date": t.transaction_date.isoformat(), "transaction_type": t.transaction_type,
                      "check_number": t.check_number, "entity": t.parent_entity.display_name if t.parent_entity else None,
                      "clear_date": t.clear_date.isoformat() if t.clear_date else None,
                      "amount": fmt(cents if t.transaction_type == "DEPOSIT" else -cents)})
    return {"as_of": as_of.isoformat(), "bank_balance": fmt(bank.current_cents(db, acct, as_of)),
            "outstanding": items, "balance": fmt(bank.available_cents(db, acct, as_of))}


def get(db: Session, ctx, txn_id: int) -> RegisterTransaction:
    t = get_scoped(db, RegisterTransaction, txn_id, ctx, "Transaction")
    if t.status == "DELETED" and "AUDITOR" not in ctx.roles:  # 1.7.3 (#53): only Auditors see deleted transactions
        raise not_found("Transaction")
    return t


def get_review(db: Session, ctx, rid: int) -> FiscalYearReview:
    r = get_scoped(db, FiscalYearReview, rid, ctx, "Review item")
    if r is None:
        raise not_found("Review item")
    return r
