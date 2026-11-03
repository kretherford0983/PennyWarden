"""2.4.0 (#254): invoice payments - the only part of the Invoices module that changes the register.

* Budgets change only when the deposit is recorded (BR-048): an open invoice touches no budget.
* **Record payment** (Register User) creates the deposit from the invoice: the amount is applied to the tax in
  proportion and to the lines in order, each on its Invoiced Income budget (continued into the deposit's Fiscal Year
  when the invoice's year differs, #89). An amount above the open balance becomes an *Overpayment* allocation.
* **Link** an existing deposit allocation that is already on an Invoiced Income budget (Register User or Invoice
  Manager); capped at the open balance; another payer than the customer is a warning to confirm. A deposit on another
  budget is re-allocated or split by a Register User first.
* With the module on, a deposit allocation on an Invoiced Income budget must be linked to an invoice: the register
  refuses one entered by hand, and a linked allocation can't change budget or amount (or be removed) until it is
  unlinked here. **Unlink** (Register User) moves the allocation to another Income budget in the same step.
* **Refund** of an overpayment (Register User): a withdrawal on the overpayment's Invoiced Income budget - the only
  BR-050 exception - capped at that invoice's unrefunded overage.
* Voiding or deleting a linked deposit re-opens the invoice in the same database transaction (BR-077).
Every change is audited atomically with the register change.
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, conflict, not_found, validation
from ..models import (Budget, Entity, FiscalYear, Invoice, InvoicePayment, RegisterTransaction, TransactionAllocation,
                      utcnow)
from ..money import fmt, parse_amount
from . import invoice_catalog as cat
from . import invoice_docs as docs
from . import invoices as inv
from ..errors import Warning_, require_confirmations

KINDS = ("PAYMENT", "OVERPAYMENT", "REFUND")


# ------------------------------------------------------------------ figures
def _live_links(db: Session, invoice_id: int) -> list[tuple[InvoicePayment, TransactionAllocation, RegisterTransaction]]:
    out = []
    for link in db.scalars(select(InvoicePayment).where(InvoicePayment.invoice_id == invoice_id,
                                                        InvoicePayment.removed_at.is_(None)).order_by(InvoicePayment.id)):
        a = db.get(TransactionAllocation, link.allocation_id)
        if a is None or a.removed_at is not None:
            continue
        t = a.transaction
        if t.status != "ACTIVE":
            continue
        out.append((link, a, t))
    return out


def figures(db: Session, i: Invoice) -> dict:
    links = _live_links(db, i.id)
    paid = sum(a.amount_cents for link, a, _t in links if link.kind == "PAYMENT")
    over = sum(a.amount_cents for link, a, _t in links if link.kind == "OVERPAYMENT")
    refunded = sum(a.amount_cents for link, a, _t in links if link.kind == "REFUND")
    total = docs.totals_of(i)["total"]
    return {"total": total, "paid": paid, "open": max(total - paid, 0), "overpaid": over, "refunded": refunded,
            "refundable": max(over - refunded, 0)}


def has_payments(db: Session, i: Invoice) -> bool:
    return any(True for _ in _live_links(db, i.id))


def refresh_status(db: Session, ctx, i: Invoice) -> None:
    """Sent / Partly paid / Paid from the linked payments (Draft, Void and Written off are left as they are)."""
    if i.status not in ("SENT", "PARTLY_PAID", "PAID"):
        return
    f = figures(db, i)
    new = "PAID" if f["paid"] >= f["total"] and f["total"] > 0 else ("PARTLY_PAID" if f["paid"] > 0 else "SENT")
    if new != i.status:
        before = i.status
        i.status = new
        db.flush()
        audit.record(db, ctx, "INVOICE_STATUS_CHANGED", "invoice", i.id, {"status": before},
                     {"status": new, "paid": fmt(f["paid"]), "total": fmt(f["total"])})


def payments_out(db: Session, i: Invoice) -> dict:
    f = figures(db, i)
    rows = []
    for link in db.scalars(select(InvoicePayment).where(InvoicePayment.invoice_id == i.id).order_by(InvoicePayment.id)):
        a = db.get(TransactionAllocation, link.allocation_id)
        t = a.transaction if a is not None else None
        rows.append({"id": link.id, "kind": link.kind, "allocation_id": link.allocation_id,
                     "transaction_id": t.id if t else None, "bank_account_id": t.bank_account_id if t else None,
                     "transaction_type": t.transaction_type if t else None,
                     "date": t.transaction_date.isoformat() if t else None, "amount": fmt(a.amount_cents) if a else None,
                     "status": t.status if t else None, "budget": cat._budget_brief(db, a.budget_id) if a else None,
                     "unlinked": link.removed_at is not None, "unlink_reason": link.remove_reason})
    return {**{k: fmt(v) for k, v in f.items()}, "links": rows}


# ------------------------------------------------------------------ register guards
def linked_allocations(db: Session, allocation_ids: list[int]) -> dict[int, str]:
    """allocation id -> link kind, for the allocations among these that are linked to an invoice."""
    if not allocation_ids:
        return {}
    return {link.allocation_id: link.kind for link in db.scalars(select(InvoicePayment).where(
        InvoicePayment.allocation_id.in_(allocation_ids), InvoicePayment.removed_at.is_(None)))}


def guard_new_plans(db: Session, ctx, txn_type: str, plans: list, invoice_flow: bool) -> None:
    """With the module on, a deposit allocation on an Invoiced Income budget comes from an invoice (Record payment or
    Link) - never entered by hand in the register."""
    if invoice_flow or txn_type != "DEPOSIT" or not inv.module_enabled(db, ctx.workspace_id):
        return
    for p in plans:
        if p.budget.invoiced_income:
            raise AppError(422, "INVOICE_PAYMENT_REQUIRED",
                           "This is an Invoiced Income budget: record the deposit with Record payment on the invoice "
                           "(or link it there), or choose another budget.")


def guard_edit(db: Session, ctx, t: RegisterTransaction, new_type: str, plans: list, existing: dict,
               linked: dict[int, str]) -> None:
    """A linked allocation keeps its budget, amount and type until it is unlinked on the invoice; a new or changed
    deposit allocation on an Invoiced Income budget is refused while the module is on."""
    kept = {p.existing.id: p for p in plans if p.existing is not None}
    for aid in linked:
        p = kept.get(aid)
        ex = existing.get(aid)
        if p is None or ex is None or new_type != t.transaction_type or p.budget.id != ex.budget_id \
                or p.amount != ex.amount_cents:
            raise conflict("LINKED_TO_INVOICE", "This line pays (or refunds) an invoice. Unlink it on the invoice "
                           "first; then it can be changed here.")
    if new_type != "DEPOSIT" or not inv.module_enabled(db, ctx.workspace_id):
        return
    for p in plans:
        if p.existing is not None and p.existing.id in linked:
            continue
        if p.budget.invoiced_income and (p.existing is None or p.existing.budget_id != p.budget.id
                                         or p.existing.amount_cents != p.amount):
            raise AppError(422, "INVOICE_PAYMENT_REQUIRED",
                           "This is an Invoiced Income budget: record or link the payment on the invoice, or choose "
                           "another budget.")


def after_transaction_change(db: Session, ctx, t: RegisterTransaction) -> None:
    """A voided or deleted deposit (or refund) changes what its invoices have received: re-open / update them."""
    ids = [a.id for a in t.allocations]
    if not ids:
        return
    inv_ids = {link.invoice_id for link in db.scalars(select(InvoicePayment).where(
        InvoicePayment.allocation_id.in_(ids), InvoicePayment.removed_at.is_(None)))}
    for iid in sorted(inv_ids):
        i = db.get(Invoice, iid)
        if i is not None:
            refresh_status(db, ctx, i)


# ------------------------------------------------------------------ record payment (Register User)
def _r(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apportion(i: Invoice, cumulative: int) -> tuple[list[int], int]:
    """How a cumulative amount paid is spread: the tax in proportion, the rest over the lines in order (each up to its
    net). Differences of two calls give one payment's parts, so successive payments always add up exactly."""
    t = docs.totals_of(i)
    total = t["total"]
    if total <= 0:
        return [0] * len(t["rows"]), 0
    cumulative = min(cumulative, total)
    tax = _r(Decimal(cumulative) * Decimal(t["tax"]) / Decimal(total)) if t["tax"] else 0
    rest = cumulative - tax
    parts = []
    for r in t["rows"]:
        take = min(rest, r["final"])
        parts.append(take)
        rest -= take
    if rest:                                   # rounding: whatever is left goes to the tax
        tax += rest
    return parts, tax


def _deposit_fy(db: Session, ws_id: int, d: dt.date) -> FiscalYear | None:
    return db.scalar(select(FiscalYear).where(FiscalYear.workspace_id == ws_id, FiscalYear.start_date <= d,
                                              FiscalYear.end_date >= d, FiscalYear.status != "CLOSED")
                     .order_by(FiscalYear.start_date))


def _budget_in(db: Session, budget_id: int, fy: FiscalYear | None) -> int:
    """The line's Invoiced Income budget, continued into the deposit's Fiscal Year when that year differs (#89);
    otherwise the line's own budget (the register's cross-year review then applies, BR-058/059)."""
    b = cat.budget_for_year(db, budget_id, fy) if fy is not None else None
    return b.id if b is not None else budget_id


def _get_open(db: Session, ctx, i: Invoice) -> None:
    if i.status not in ("SENT", "PARTLY_PAID", "PAID"):
        raise conflict("INVALID_STATE", "Payments are recorded on a sent invoice (not a draft, a void or a "
                       "written-off one).")
    if i.write_off_status == "PENDING":
        raise conflict("WRITE_OFF_PENDING", "A write-off is waiting for a decision; decide it first.")


def record_payment(db: Session, ctx, i: Invoice, body) -> RegisterTransaction:
    from ..schemas import AllocationIn, TransactionCreateIn
    from . import register as reg
    inv.require_module(db, ctx)
    ctx.require("invoice.record_payment")
    _get_open(db, ctx, i)
    try:
        amount = parse_amount(body.amount, allow_zero=False)
    except ValueError as e:
        raise validation(str(e), "amount") from None
    f = figures(db, i)
    pay = min(amount, f["open"])
    over = amount - pay
    if pay == 0 and not body.confirm_overpayment:
        raise AppError(409, "CONFIRMATION_REQUIRED", "The invoice is already paid; the whole amount would be an "
                       "overpayment.", warnings=[{"code": "OVERPAYMENT", "message": "The invoice is already paid.",
                                                  "details": {}}])
    d = body.transaction_date or dt.date.today()
    fy = _deposit_fy(db, ctx.workspace_id, d)
    before, before_tax = apportion(i, f["paid"])
    after, after_tax = apportion(i, f["paid"] + pay)
    lines = list(docs.totals_of(i)["rows"])
    allocs: list[tuple[AllocationIn, str]] = []
    num = docs.display_number(i)
    for r, b0, b1 in zip(lines, before, after):
        part = b1 - b0
        if part > 0:
            allocs.append((AllocationIn(budget_id=_budget_in(db, r["line"].budget_id, fy), amount=fmt(part),
                                        entity_id=i.customer_entity_id, fiscal_year_id=None,
                                        description=f"{num}: {r['line'].description}"[:500]), "PAYMENT"))
    if after_tax - before_tax > 0:
        allocs.append((AllocationIn(budget_id=_budget_in(db, i.tax_budget_id, fy), amount=fmt(after_tax - before_tax),
                                    entity_id=i.customer_entity_id, description=f"{num}: {i.tax_name or 'Sales tax'}"[:500]),
                       "PAYMENT"))
    if over > 0:
        first = lines[0]["line"].budget_id if lines else i.tax_budget_id
        if over > 0 and not body.confirm_overpayment and pay > 0:
            raise AppError(409, "CONFIRMATION_REQUIRED", f"{fmt(over)} more than the open balance: it will be recorded "
                           "as an overpayment (it can be refunded).",
                           warnings=[{"code": "OVERPAYMENT", "message": "Amount above the open balance.",
                                      "details": {"overpayment": fmt(over)}}])
        allocs.append((AllocationIn(budget_id=_budget_in(db, first, fy), amount=fmt(over),
                                    entity_id=i.customer_entity_id, description=f"Overpayment — {num}"), "OVERPAYMENT"))
    data = TransactionCreateIn(bank_account_id=body.bank_account_id, transaction_type="DEPOSIT", transaction_date=d,
                               clear_date=body.clear_date, entity_id=i.customer_entity_id,
                               notes=(body.notes or f"Payment of invoice {num}")[:4000],
                               allocations=[a for a, _k in allocs], confirmations=body.confirmations)
    t = reg.create(db, ctx, data, invoice_flow={})
    created = sorted(t.live_allocations, key=lambda a: a.id)
    for a, (_ai, kind) in zip(created, allocs):
        db.add(InvoicePayment(workspace_id=ctx.workspace_id, invoice_id=i.id, allocation_id=a.id, kind=kind,
                              created_by_user_id=ctx.user.id))
    db.flush()
    audit.record(db, ctx, "INVOICE_PAYMENT_RECORDED", "invoice", i.id, {"paid": fmt(f["paid"])},
                 {"transaction_id": t.id, "amount": fmt(amount), "paid_now": fmt(pay), "overpayment": fmt(over),
                  "allocation_ids": [a.id for a in created]})
    refresh_status(db, ctx, i)
    return t


# ------------------------------------------------------------------ link an existing deposit
def link(db: Session, ctx, i: Invoice, allocation_id: int, confirmations: list[str]) -> InvoicePayment:
    from . import register as reg
    inv.require_module(db, ctx)
    ctx.require("invoice.link_payment")
    _get_open(db, ctx, i)
    a = db.get(TransactionAllocation, allocation_id) if isinstance(allocation_id, int) else None
    if a is None or a.removed_at is not None or a.transaction.workspace_id != ctx.workspace_id:
        raise not_found("Allocation")
    t = a.transaction
    if t.status != "ACTIVE" or t.transaction_type != "DEPOSIT":
        raise conflict("INVALID_STATE", "Only a line of an active deposit can pay an invoice.")
    b = db.get(Budget, a.budget_id)
    if not b.invoiced_income:
        raise AppError(422, "NOT_INVOICED_INCOME", "This deposit line is not on an Invoiced Income budget. A Register "
                       "User re-allocates it (or splits off the invoice part) first, then links it.")
    if reg.is_closed_protected(db, t):
        raise conflict("FISCAL_YEAR_CLOSED", "The deposit is in a Closed Fiscal Year; it can't be linked.")
    if linked_allocations(db, [a.id]):
        raise conflict("ALREADY_LINKED", "This deposit line is already linked to an invoice.")
    f = figures(db, i)
    if a.amount_cents > f["open"]:
        raise AppError(422, "OVER_OPEN_BALANCE", f"The line is {fmt(a.amount_cents)} but the invoice's open balance is "
                       f"{fmt(f['open'])}. A Register User splits the deposit so the invoice part matches, then links it.")
    payer = a.entity_id or t.parent_entity_id
    warnings = []
    if payer != i.customer_entity_id:
        e = db.get(Entity, payer) if payer else None
        warnings.append(Warning_("THIRD_PARTY_PAYER", f"The deposit is from {e.display_name if e else 'someone else'}, "
                                 "not the invoice's customer. Link it anyway?"))
    require_confirmations(warnings, confirmations)
    p = InvoicePayment(workspace_id=ctx.workspace_id, invoice_id=i.id, allocation_id=a.id, kind="PAYMENT",
                       created_by_user_id=ctx.user.id)
    db.add(p)
    db.flush()
    audit.record(db, ctx, "INVOICE_PAYMENT_LINKED", "invoice", i.id, {"paid": fmt(f["paid"])},
                 {"allocation_id": a.id, "transaction_id": t.id, "amount": fmt(a.amount_cents),
                  "confirmed_warnings": [w.code for w in warnings]})
    refresh_status(db, ctx, i)
    return p


def unlink(db: Session, ctx, i: Invoice, link_id: int, move_to_budget_id: int, reason: str) -> None:
    """Register User: the allocation leaves the invoice and moves to another (not Invoiced Income) Income budget in
    the same step, so no unlinked line stays on an Invoiced Income budget."""
    from . import budgets as bsvc
    from . import register as reg
    inv.require_module(db, ctx)
    ctx.require("transaction.manage")
    p = db.get(InvoicePayment, link_id) if isinstance(link_id, int) else None
    if p is None or p.invoice_id != i.id or p.removed_at is not None:
        raise not_found("Payment link")
    if p.kind == "REFUND":
        raise conflict("INVALID_STATE", "A refund stays with its invoice; void the refund in the register instead.")
    reason = (reason or "").strip()
    if not reason:
        raise validation("Say why it is unlinked.", "reason")
    a = db.get(TransactionAllocation, p.allocation_id)
    t = a.transaction
    if reg.is_closed_protected(db, t):
        raise conflict("FISCAL_YEAR_CLOSED", "The deposit is in a Closed Fiscal Year; it can't change.")
    if t.status != "ACTIVE":
        raise conflict("INVALID_STATE", "The deposit is not active.")
    nb, _w = bsvc.resolve_for_allocation(db, ctx, move_to_budget_id, "DEPOSIT", False)
    if nb.invoiced_income:
        raise validation("Move it to a budget that is not Invoiced Income.", "move_to_budget_id")
    before = {"budget_id": a.budget_id, "link": p.kind}
    reg_before = reg.snapshot(t)
    a.budget_id = nb.id
    a.updated_by_user_id = ctx.user.id
    p.removed_at, p.removed_by_user_id, p.remove_reason = utcnow(), ctx.user.id, reason[:500]
    db.flush()
    db.expire(t, ["allocations"])
    audit.record(db, ctx, "TRANSACTION_UPDATED", "register_transaction", t.id, reg_before,
                 {**reg.snapshot(t), "reason": f"Unlinked from invoice {docs.display_number(i)}: {reason}"})
    audit.record(db, ctx, "INVOICE_PAYMENT_UNLINKED", "invoice", i.id, before,
                 {"allocation_id": a.id, "budget_id": nb.id, "reason": reason})
    refresh_status(db, ctx, i)


# ------------------------------------------------------------------ refund an overpayment (Register User)
def refund(db: Session, ctx, i: Invoice, body) -> RegisterTransaction:
    from ..schemas import AllocationIn, TransactionCreateIn
    from . import register as reg
    inv.require_module(db, ctx)
    ctx.require("invoice.record_payment")
    try:
        amount = parse_amount(body.amount, allow_zero=False)
    except ValueError as e:
        raise validation(str(e), "amount") from None
    f = figures(db, i)
    if amount > f["refundable"]:
        raise AppError(422, "OVER_REFUNDABLE", f"At most {fmt(f['refundable'])} can be refunded on this invoice "
                       "(its overpayment not yet refunded).")
    over = [a for link, a, _t in _live_links(db, i.id) if link.kind == "OVERPAYMENT"]
    budget_id = over[0].budget_id
    num = docs.display_number(i)
    data = TransactionCreateIn(bank_account_id=body.bank_account_id, transaction_type="WITHDRAWAL",
                               transaction_date=body.transaction_date or dt.date.today(), clear_date=body.clear_date,
                               entity_id=i.customer_entity_id, check_number=body.check_number,
                               notes=(body.notes or f"Refund of the overpayment on invoice {num}")[:4000],
                               allocations=[AllocationIn(budget_id=budget_id, amount=fmt(amount),
                                                         description=f"Refund — overpayment on {num}")],
                               electronic_payment=body.electronic_payment, payment_method=body.payment_method,
                               payment_reference=body.payment_reference, confirmations=body.confirmations)
    t = reg.create(db, ctx, data, invoice_flow={"refund_ok": [budget_id]})
    a = t.live_allocations[0]
    db.add(InvoicePayment(workspace_id=ctx.workspace_id, invoice_id=i.id, allocation_id=a.id, kind="REFUND",
                          created_by_user_id=ctx.user.id))
    db.flush()
    audit.record(db, ctx, "INVOICE_REFUND_RECORDED", "invoice", i.id, {"refundable": fmt(f["refundable"])},
                 {"transaction_id": t.id, "amount": fmt(amount), "allocation_id": a.id})
    return t


def candidates(db: Session, ctx, i: Invoice) -> list[dict]:
    """Deposit lines that could be linked: active, unlinked, on an Invoiced Income budget, not in a closed year."""
    from . import register as reg
    inv.require_module(db, ctx)
    ctx.require("invoice.link_payment")
    out = []
    q = (select(TransactionAllocation).join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
         .join(Budget, Budget.id == TransactionAllocation.budget_id)
         .where(RegisterTransaction.workspace_id == ctx.workspace_id, RegisterTransaction.status == "ACTIVE",
                RegisterTransaction.transaction_type == "DEPOSIT", TransactionAllocation.removed_at.is_(None),
                Budget.invoiced_income.is_(True)).order_by(RegisterTransaction.transaction_date.desc()).limit(200))
    linked = None
    for a in db.scalars(q):
        if linked is None:
            linked = set()
        if linked_allocations(db, [a.id]) or reg.is_closed_protected(db, a.transaction):
            continue
        e = db.get(Entity, a.entity_id or a.transaction.parent_entity_id) if (a.entity_id or a.transaction.parent_entity_id) else None
        out.append({"allocation_id": a.id, "transaction_id": a.transaction_id, "date": a.transaction.transaction_date.isoformat(),
                    "amount": fmt(a.amount_cents), "entity": e.display_name if e else None,
                    "budget": cat._budget_brief(db, a.budget_id), "description": a.description})
    return out
