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
                     "unlinked": link.removed_at is not None, "unlink_reason": link.remove_reason,
                     "credit_from": ({"id": link.credit_from_invoice_id,
                                      "number": docs.display_number(db.get(Invoice, link.credit_from_invoice_id))}
                                     if link.credit_from_invoice_id else None)})
    credit = sum(a.amount_cents for link, a, _t in _live_links(db, i.id) if link.credit_from_invoice_id)
    return {**{k: fmt(v) for k, v in f.items()}, "links": rows, "credit_applied": fmt(credit),     # 2.4.0 (#534)
            "due": fmt(f["open"]),
            "customer_credit": credit_out(db, i.workspace_id, i.customer_entity_id, i.id)}


# ------------------------------------------------------------------ register guards
def linked_allocations(db: Session, allocation_ids: list[int]) -> dict[int, str]:
    """allocation id -> link kind, for the allocations among these that are linked to an invoice."""
    if not allocation_ids:
        return {}
    return {link.allocation_id: link.kind for link in db.scalars(select(InvoicePayment).where(
        InvoicePayment.allocation_id.in_(allocation_ids), InvoicePayment.removed_at.is_(None)))}


def allocation_invoices(db: Session, allocation_ids: list[int]) -> dict[int, dict]:
    """2.4.0 (#533): allocation id -> the invoice it pays (or refunds), for the register's lines."""
    if not allocation_ids:
        return {}
    out = {}
    for link in db.scalars(select(InvoicePayment).where(InvoicePayment.allocation_id.in_(allocation_ids),
                                                        InvoicePayment.removed_at.is_(None))):
        i = db.get(Invoice, link.invoice_id)
        out[link.allocation_id] = {"id": i.id, "number": docs.display_number(i), "kind": link.kind}
    return out


def guard_new_plans(db: Session, ctx, txn_type: str, plans: list, invoice_flow: bool,
                    generated: set[int] | None = None) -> None:
    """With the module on, a deposit allocation on an Invoiced Income budget comes from an invoice (Record payment,
    Link, or #533 Apply to invoice in the register) - never entered by hand in the register."""
    if invoice_flow or txn_type != "DEPOSIT" or not inv.module_enabled(db, ctx.workspace_id):
        return
    for p in plans:
        if generated and id(p.data) in generated:
            continue
        if p.budget.invoiced_income:
            raise AppError(422, "INVOICE_PAYMENT_REQUIRED",
                           "This is an Invoiced Income budget: use Apply to invoice… on the allocation (or Record "
                           "payment on the invoice), or choose another budget.")


def guard_edit(db: Session, ctx, t: RegisterTransaction, new_type: str, plans: list, existing: dict,
               linked: dict[int, str], generated: set[int] | None = None) -> None:
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
        if generated and id(p.data) in generated:
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
    parts, taxes = apportion_rates(i, cumulative)
    return parts, sum(taxes)


def apportion_rates(i: Invoice, cumulative: int) -> tuple[list[int], list[int]]:
    """2.4.0 polish (#487): as `apportion`, with the tax part split over the invoice's rates - filled in the order
    the rates appear (each up to its tax), like the lines - so each rate's money goes to its own budget and the
    parts never go down from one payment to the next."""
    t = docs.totals_of(i)
    total = t["total"]
    rates = t["taxes"]
    if total <= 0:
        return [0] * len(t["rows"]), [0] * len(rates)
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
    out, left = [], tax
    for x in rates:
        take = min(left, x["tax"])
        out.append(take)
        left -= take
    if left and out:                           # cannot happen once paid in full; keeps the sum exact
        out[-1] += left
    return parts, out


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


def _invoice_allocations(db: Session, i: Invoice, paid: int, pay: int, over: int, fy: FiscalYear | None,
                         entity_id: int | None) -> list[tuple]:
    """The deposit lines that pay `pay` of an invoice already paid `paid`: the lines' share on their Invoiced Income
    budgets and each tax rate's on its own (#487), as the difference of two cumulative apportionments; `over` (an
    overpayment) on the first line's budget. #523: shared by Record payment and the payment for several invoices."""
    from ..schemas import AllocationIn
    before, before_tax = apportion_rates(i, paid)
    after, after_tax = apportion_rates(i, paid + pay)
    tt = docs.totals_of(i)
    lines = list(tt["rows"])
    allocs: list[tuple[AllocationIn, str]] = []
    num = docs.display_number(i)
    for r, b0, b1 in zip(lines, before, after):
        part = b1 - b0
        if part > 0:
            allocs.append((AllocationIn(budget_id=_budget_in(db, r["line"].budget_id, fy), amount=fmt(part),
                                        entity_id=entity_id, fiscal_year_id=None,
                                        description=f"{num}: {r['line'].description}"[:500]), "PAYMENT"))
    for x, b0, b1 in zip(tt["taxes"], before_tax, after_tax):        # 2.4.0 polish (#487): each rate to its budget
        if b1 - b0 > 0:
            allocs.append((AllocationIn(budget_id=_budget_in(db, x["budget_id"], fy), amount=fmt(b1 - b0),
                                        entity_id=entity_id, description=f"{num}: {x['name']}"[:500]), "PAYMENT"))
    if over > 0:
        first = lines[0]["line"].budget_id if lines else (tt["taxes"][0]["budget_id"] if tt["taxes"] else None)
        allocs.append((AllocationIn(budget_id=_budget_in(db, first, fy), amount=fmt(over), entity_id=entity_id,
                                    description=f"Overpayment — {num}"), "OVERPAYMENT"))
    return allocs


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
    if over > 0 and not body.confirm_overpayment and pay > 0:
        raise AppError(409, "CONFIRMATION_REQUIRED", f"{fmt(over)} more than the open balance: it will be recorded "
                       "as an overpayment (it can be refunded).",
                       warnings=[{"code": "OVERPAYMENT", "message": "Amount above the open balance.",
                                  "details": {"overpayment": fmt(over)}}])
    d = body.transaction_date or dt.date.today()
    fy = _deposit_fy(db, ctx.workspace_id, d)
    allocs = _invoice_allocations(db, i, f["paid"], pay, over, fy, i.customer_entity_id)
    num = docs.display_number(i)
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


# ------------------------------------------------------------------ 2.4.0 (#523): one payment, several invoices
def open_for_payment(db: Session, ctx, customer_entity_id: int | None, number: str | None) -> dict:
    """The open invoices a payment can go to (sent or partly paid, no write-off waiting), oldest due date first: a
    customer's, or - from an invoice number typed off a payment stub - that invoice's customer's."""
    inv.require_module(db, ctx)
    ctx.require("invoice.record_payment")
    found = None
    if number and number.strip():
        q = number.strip().lower()
        for i in db.scalars(select(Invoice).where(Invoice.workspace_id == ctx.workspace_id,
                                                  Invoice.status != "DRAFT")):
            if (docs.display_number(i) or "").lower() == q:
                found = i
                break
        if found is None:
            raise not_found("Invoice")
        customer_entity_id = found.customer_entity_id
    if customer_entity_id is None:
        raise validation("Choose a customer or type an invoice number.", "customer_entity_id")
    e = db.get(Entity, customer_entity_id)
    if e is None or e.workspace_id != ctx.workspace_id:
        raise not_found("Entity")
    rows = []
    for i in db.scalars(select(Invoice).where(Invoice.workspace_id == ctx.workspace_id,
                                              Invoice.customer_entity_id == customer_entity_id,
                                              Invoice.status.in_(("SENT", "PARTLY_PAID")))):
        if i.write_off_status == "PENDING":
            continue
        f = figures(db, i)
        if f["open"] <= 0:
            continue
        rows.append({"id": i.id, "number": docs.display_number(i), "status": i.status,
                     "invoice_date": i.invoice_date.isoformat() if i.invoice_date else None,
                     "due_date": i.due_date.isoformat() if i.due_date else None,
                     "total": fmt(f["total"]), "paid": fmt(f["paid"]), "open": fmt(f["open"]),
                     "customer_entity_id": i.customer_entity_id})
    rows.sort(key=lambda r: (r["due_date"] or "9999", r["invoice_date"] or "", r["id"]))
    return {"customer": {"id": e.id, "name": e.display_name}, "invoices": rows,
            "found_invoice_id": found.id if found is not None else None,
            "credit": credit_out(db, ctx.workspace_id, e.id)}                      # 2.4.0 (#534)


def record_multi(db: Session, ctx, body) -> tuple[RegisterTransaction, list[Invoice]]:
    """One deposit paying several invoices (decided with Kyle 2026-11-04): each invoice gets the lines Record payment
    would give it, linked to it; the extra above the balances (confirmed) is an overpayment on the chosen invoice; a
    payer other than an invoice's customer is the THIRD_PARTY_PAYER warning; the deposit's entity is the payer.
    Void and unlink stay per invoice (the existing rules)."""
    from ..schemas import TransactionCreateIn
    from . import register as reg
    inv.require_module(db, ctx)
    ctx.require("invoice.record_payment")
    ids = [x.invoice_id for x in body.items]
    if len(set(ids)) != len(ids):
        raise validation("Each invoice can be listed once.", "items")
    parts: list[tuple[Invoice, int, dict]] = []
    for n, x in enumerate(body.items):
        i = docs.get(db, ctx, x.invoice_id)
        _get_open(db, ctx, i)
        try:
            amount = parse_amount(x.amount, allow_zero=False)
        except ValueError as e:
            raise validation(str(e), f"items.{n}.amount") from None
        f = figures(db, i)
        if amount > f["open"]:
            raise AppError(422, "OVER_OPEN_BALANCE", f"{fmt(amount)} for invoice {docs.display_number(i)} is more than "
                           f"its open balance of {fmt(f['open'])}. Put the extra as an overpayment instead.",
                           errors=[{"field": f"items.{n}.amount", "message": "More than the open balance."}])
        parts.append((i, amount, f))
    over = 0
    if body.overpayment not in (None, "", "0", "0.00"):
        try:
            over = parse_amount(body.overpayment, allow_zero=True)
        except ValueError as e:
            raise validation(str(e), "overpayment") from None
    target = None
    if over > 0:
        target = next((i for i, _a, _f in parts if i.id == body.overpayment_invoice_id), None)
        if target is None:
            raise validation("Choose which of these invoices gets the overpayment.", "overpayment_invoice_id")
        if not body.confirm_overpayment:
            raise AppError(409, "CONFIRMATION_REQUIRED", f"{fmt(over)} more than the invoices' balances: it will be "
                           f"recorded as an overpayment on invoice {docs.display_number(target)} (it can be refunded).",
                           warnings=[{"code": "OVERPAYMENT", "message": "Amount above the open balances.",
                                      "details": {"overpayment": fmt(over)}}])
    customers = {i.customer_entity_id for i, _a, _f in parts}
    payer = body.payer_entity_id
    if payer is None:
        if len(customers) > 1:
            raise validation("These invoices are for different customers: choose who paid.", "payer_entity_id")
        payer = next(iter(customers))
    pe = db.get(Entity, payer)
    if pe is None or pe.workspace_id != ctx.workspace_id:
        raise not_found("Entity")
    others = [i for i, _a, _f in parts if i.customer_entity_id != payer]
    warnings = []
    if others:
        nums = ", ".join(docs.display_number(i) for i in others)
        warnings.append(Warning_("THIRD_PARTY_PAYER", f"The payment is from {pe.display_name}, not the customer of "
                                 f"invoice{'s' if len(others) > 1 else ''} {nums}. Record it anyway?"))
    require_confirmations(warnings, body.confirmations)
    d = body.transaction_date or dt.date.today()
    fy = _deposit_fy(db, ctx.workspace_id, d)
    plan: list[tuple[Invoice, tuple]] = []
    for i, amount, f in parts:
        for a in _invoice_allocations(db, i, f["paid"], amount, over if i is target else 0, fy, payer):
            plan.append((i, a))
    if len(plan) > 100:
        raise validation("Too many deposit lines for one payment (at most 100): record it in two parts.", "items")
    nums = ", ".join(docs.display_number(i) for i, _a, _f in parts)
    data = TransactionCreateIn(bank_account_id=body.bank_account_id, transaction_type="DEPOSIT", transaction_date=d,
                               clear_date=body.clear_date, entity_id=payer,
                               notes=(body.notes or f"Payment of invoices {nums}")[:4000],
                               allocations=[a for _i, (a, _k) in plan], confirmations=body.confirmations)
    t = reg.create(db, ctx, data, invoice_flow={})
    created = sorted(t.live_allocations, key=lambda a: a.id)
    for a, (i, (_ai, kind)) in zip(created, plan):
        db.add(InvoicePayment(workspace_id=ctx.workspace_id, invoice_id=i.id, allocation_id=a.id, kind=kind,
                              created_by_user_id=ctx.user.id))
    db.flush()
    total = sum(a for _i, a, _f in parts) + over
    for i, amount, f in parts:
        mine = [a.id for a, (j, _x) in zip(created, plan) if j is i]
        audit.record(db, ctx, "INVOICE_PAYMENT_RECORDED", "invoice", i.id, {"paid": fmt(f["paid"])},
                     {"transaction_id": t.id, "amount": fmt(amount + (over if i is target else 0)),
                      "paid_now": fmt(amount), "overpayment": fmt(over if i is target else 0),
                      "allocation_ids": mine, "deposit_total": fmt(total), "invoices_in_deposit": len(parts),
                      "confirmed_warnings": [w.code for w in warnings]})
        refresh_status(db, ctx, i)
    return t, [i for i, _a, _f in parts]


# ------------------------------------------------------------------ 2.4.0 (#533): Apply to invoice in the register
class Applied:
    """What expand_applications made of a deposit's "Apply to invoice" allocations: the allocations to save (the
    applied parts replaced by the invoices' splits), which of them are generated, and what to do once saved."""

    def __init__(self):
        self.allocations: list = []
        self.generated: set[int] = set()          # id() of the generated AllocationIn objects
        self.links: list[tuple] = []               # (AllocationIn, Invoice, kind[, credit_from_invoice_id])
        self.refunds: list[tuple] = []             # (Invoice, cents)
        self.audit: list[tuple] = []               # (Invoice, paid before, applied, overpayment)
        self.warnings: list = []
        self.created: dict[int, TransactionAllocation] = {}
        self.unlink: list = []                     # #534: links set aside for a system re-allocation
        self.reason: str = ""


def expand_applications(db: Session, ctx, txn_type: str, txn_date: dt.date, parent_entity_id: int | None,
                        allocs_in: list) -> Applied | None:
    """Decided with Kyle 2026-11-06: an allocation applied to invoices becomes, when saved, each invoice's splits (its
    lines' Invoiced Income budgets and tax, as Record payment gives them) linked to the invoice; the extra above
    them stays on the allocation's budget (BUDGET), is an overpayment on an invoice kept as credit (CREDIT, #534) or
    is refunded at once (REFUND: an overpayment, then a refund withdrawal). None when nothing is applied."""
    if not any(getattr(a, "apply_to", None) for a in allocs_in):
        return None
    inv.require_module(db, ctx)
    ctx.require("invoice.record_payment")
    if txn_type != "DEPOSIT":
        raise validation("Only a deposit can pay an invoice.", "allocations")
    out = Applied()
    fy = _deposit_fy(db, ctx.workspace_id, txn_date)
    paid_now: dict[int, int] = {}                 # invoice id -> applied earlier in this deposit
    third: list[str] = []
    for n, a in enumerate(allocs_in):
        if not a.apply_to:
            if a.apply_extra is not None or a.apply_extra_invoice_id is not None:
                raise validation("Nothing is applied to an invoice on this line.", f"allocations.{n}.apply_to")
            out.allocations.append(a)
            continue
        try:
            total = parse_amount(a.amount, allow_zero=False)
        except ValueError as e:
            raise validation(str(e), f"allocations.{n}.amount") from None
        parts: list[tuple[Invoice, int]] = []
        seen: set[int] = set()
        for m, x in enumerate(a.apply_to):
            if x.invoice_id in seen:
                raise validation("Each invoice can be listed once on a line.", f"allocations.{n}.apply_to.{m}")
            seen.add(x.invoice_id)
            i = docs.get(db, ctx, x.invoice_id)
            _get_open(db, ctx, i)
            try:
                amt = parse_amount(x.amount, allow_zero=False)
            except ValueError as e:
                raise validation(str(e), f"allocations.{n}.apply_to.{m}.amount") from None
            f = figures(db, i)
            open_left = f["open"] - paid_now.get(i.id, 0)
            if amt > open_left:
                raise AppError(422, "OVER_OPEN_BALANCE", f"{fmt(amt)} for invoice {docs.display_number(i)} is more "
                               f"than its open balance of {fmt(open_left)}.",
                               errors=[{"field": f"allocations.{n}.apply_to.{m}.amount", "message": "More than the open balance."}])
            parts.append((i, amt))
        applied = sum(x for _i, x in parts)
        if applied > total:
            raise validation(f"{fmt(applied)} is applied to invoices but the line is {fmt(total)}.",
                             f"allocations.{n}.apply_to")
        extra = total - applied
        kind = a.apply_extra or ("BUDGET" if extra else None)
        target = None
        if extra and kind in ("CREDIT", "REFUND"):
            target = next((i for i, _x in parts if i.id == a.apply_extra_invoice_id), parts[-1][0])
        payer = a.entity_id or parent_entity_id
        for i, _x in parts:
            if payer and payer != i.customer_entity_id:
                third.append(docs.display_number(i))
        # the invoices' splits, in order; each continues from what the invoice has been paid (and earlier lines)
        for i, x in parts:
            f = figures(db, i)
            before = f["paid"] + paid_now.get(i.id, 0)
            over = extra if (i is target) else 0
            for ai, k in _invoice_allocations(db, i, before, x, over, fy, a.entity_id):
                ai = ai.model_copy(update={"notes": a.notes, "no_attachment": a.no_attachment,
                                           "no_attachment_reason": a.no_attachment_reason})
                out.allocations.append(ai)
                out.generated.add(id(ai))
                out.links.append((ai, i, k))
            paid_now[i.id] = paid_now.get(i.id, 0) + x
            out.audit.append((i, before, x, over))
        if extra and kind == "BUDGET":
            b = db.get(Budget, a.budget_id)
            if b is None or b.invoiced_income:
                raise validation("Choose a budget that is not Invoiced Income for the rest of this line "
                                 f"({fmt(extra)}).", f"allocations.{n}.budget_id")
            out.allocations.append(a.model_copy(update={"amount": fmt(extra), "apply_to": None, "apply_extra": None,
                                                        "apply_extra_invoice_id": None}))
        elif extra:
            out.warnings.append(Warning_("OVERPAYMENT", f"{fmt(extra)} more than the invoices' balances: it will be "
                                         f"recorded as an overpayment on invoice {docs.display_number(target)}"
                                         + (" and refunded at once." if kind == "REFUND" else " (kept as credit).")))
            if kind == "REFUND":
                out.refunds.append((target, extra))
    if third:
        out.warnings.append(Warning_("THIRD_PARTY_PAYER", "The payment is not from the customer of invoice"
                                     f"{'s' if len(third) > 1 else ''} {', '.join(sorted(set(third)))}. Record it anyway?"))
    if len(out.allocations) > 100:
        raise validation("Too many deposit lines (at most 100): record it in two parts.", "allocations")
    return out


def finish_applications(db: Session, ctx, t: RegisterTransaction, applied: Applied) -> None:
    """After the deposit is saved: link each generated line to its invoice, audit, update the invoices' status and
    write the refunds asked for."""
    from ..schemas import InvoiceRefundIn
    for ai, i, kind, *src in applied.links:
        a = applied.created.get(id(ai))
        if a is None:                              # not saved (a rolled-back no-op): nothing to link
            continue
        db.add(InvoicePayment(workspace_id=ctx.workspace_id, invoice_id=i.id, allocation_id=a.id, kind=kind,
                              credit_from_invoice_id=src[0] if src else None, created_by_user_id=ctx.user.id))
    db.flush()
    for i, before, x, over in applied.audit:
        mine = [applied.created[id(ai)].id for ai, j, _k, *_s in applied.links if j is i and id(ai) in applied.created]
        audit.record(db, ctx, "INVOICE_PAYMENT_RECORDED", "invoice", i.id, {"paid": fmt(before)},
                     {"transaction_id": t.id, "amount": fmt(x + over), "paid_now": fmt(x), "overpayment": fmt(over),
                      "allocation_ids": mine, "from_register": True})
        refresh_status(db, ctx, i)
    for i, cents in applied.refunds:               # Kyle: the system starts the reimbursement at once
        r = refund(db, ctx, i, InvoiceRefundIn(bank_account_id=t.bank_account_id, amount=fmt(cents),
                                               transaction_date=t.transaction_date,
                                               notes=f"Refund of the overpayment in deposit #{t.id} on invoice "
                                                     f"{docs.display_number(i)}"))
        refresh_status(db, ctx, i)
        assert r is not None


# ------------------------------------------------------------------ 2.4.0 (#534): customer account credit
def _system_update(db: Session, ctx, t: RegisterTransaction, applied: Applied) -> bool:
    """A register edit made by the system (credit applied / taken back): every warning the edit raises (a cleared
    transaction, a Fiscal Year review...) is accepted, as the user's action that triggered it decided; in a savepoint,
    so a refused edit (closed year, ...) changes nothing. True when it was made."""
    from ..schemas import TransactionUpdateIn
    from . import register as reg
    codes: list[str] = []
    for _attempt in range(2):
        sp = db.begin_nested()
        try:
            for x in applied.unlink:
                x.removed_at, x.removed_by_user_id, x.remove_reason = utcnow(), ctx.user.id, applied.reason
            db.flush()
            data = TransactionUpdateIn(allocations=applied.allocations, confirmations=codes)
            reg._update(db, ctx, t, data, applied)
            finish_applications(db, ctx, t, applied)
            sp.commit()
            return True
        except AppError as e:
            sp.rollback()
            if e.code != "CONFIRMATION_REQUIRED" or codes:
                return False
            codes = [w["code"] for w in (e.extra.get("warnings") or [])]
    return False


def credit_sources(db: Session, ws_id: int, customer_id: int, exclude_invoice_id: int | None = None) -> list[dict]:
    """The customer's credit (decision 2: every overpayment not refunded), oldest first: each invoice's refundable
    overpayment and the deposit lines that hold it."""
    from . import register as reg
    out = []
    for i in db.scalars(select(Invoice).where(Invoice.workspace_id == ws_id, Invoice.customer_entity_id == customer_id,
                                              Invoice.id != (exclude_invoice_id or -1))):
        f = figures(db, i)
        if f["refundable"] <= 0:
            continue
        lines = sorted(((link, a, t) for link, a, t in _live_links(db, i.id) if link.kind == "OVERPAYMENT"),
                       key=lambda x: (x[2].transaction_date, x[1].id))
        usable = [(link, a, t) for link, a, t in lines if t.status == "ACTIVE" and not reg.is_closed_protected(db, t)]
        out.append({"invoice": i, "amount": f["refundable"], "lines": usable, "first": lines[0][2].transaction_date
                    if lines else dt.date.max, "usable": min(f["refundable"], sum(a.amount_cents for _l, a, _t in usable))})
    out.sort(key=lambda x: (x["first"], x["invoice"].id))
    return out


def credit_out(db: Session, ws_id: int, customer_id: int | None, exclude_invoice_id: int | None = None) -> dict:
    if not customer_id:
        return {"total": "0.00", "usable": "0.00", "invoices": []}
    src = credit_sources(db, ws_id, customer_id, exclude_invoice_id)
    return {"total": fmt(sum(x["amount"] for x in src)), "usable": fmt(sum(x["usable"] for x in src)),
            "invoices": [{"id": x["invoice"].id, "number": docs.display_number(x["invoice"]), "amount": fmt(x["amount"]),
                          "usable": fmt(x["usable"])} for x in src]}


def apply_credit(db: Session, ctx, target: Invoice) -> int:
    """Decided with Kyle 2026-11-06: the customer's credit is applied when an invoice is sent, oldest first, up to
    what the invoice still owes. Each credit is the overpayment line of the deposit that brought it: that line is
    re-allocated on its deposit - the applied part becomes this invoice's splits (linked, remembering where the credit
    came from), the rest stays the overpayment. The deposit's total doesn't change. A credit on a deposit in a Closed
    Fiscal Year can't be re-allocated (it can still be refunded). Returns the cents applied."""
    from ..schemas import AllocationIn
    if target.status not in ("SENT", "PARTLY_PAID") or target.write_off_status == "PENDING":
        return 0
    need = figures(db, target)["open"]
    done = 0
    for src in credit_sources(db, ctx.workspace_id, target.customer_entity_id, target.id):
        left_on_invoice = src["amount"]
        for link, a, t in src["lines"]:
            if need - done <= 0 or left_on_invoice <= 0:
                break
            take = min(a.amount_cents, left_on_invoice, need - done)
            if take <= 0:
                continue
            fy = _deposit_fy(db, ctx.workspace_id, t.transaction_date)
            ap = Applied()
            ap.reason = f"Applied as credit to invoice {docs.display_number(target)}"
            ap.unlink = [link]
            for x in t.live_allocations:
                ai = AllocationIn(id=x.id, budget_id=x.budget_id, entity_id=x.entity_id, invoice_number=x.invoice_number,
                                  invoice_date=x.invoice_date, description=x.description, amount=fmt(x.amount_cents),
                                  notes=x.notes, fiscal_year_id=x.budget.fiscal_year_id)
                if x.id != a.id:
                    ap.allocations.append(ai)
                    continue
                if a.amount_cents > take:                       # the rest stays the overpayment
                    rest = ai.model_copy(update={"amount": fmt(a.amount_cents - take)})
                    ap.allocations.append(rest)
                    ap.generated.add(id(rest))
                    ap.links.append((rest, src["invoice"], "OVERPAYMENT"))
                paid_before = figures(db, target)["paid"]
                for gi, _k in _invoice_allocations(db, target, paid_before, take, 0, fy, a.entity_id):
                    gi = gi.model_copy(update={"description": f"{gi.description} (credit from "
                                                              f"{docs.display_number(src['invoice'])})"[:500]})
                    ap.allocations.append(gi)
                    ap.generated.add(id(gi))
                    ap.links.append((gi, target, "PAYMENT", src["invoice"].id))
                ap.audit.append((target, paid_before, take, 0))
            if _system_update(db, ctx, t, ap):
                done += take
                left_on_invoice -= take
                audit.record(db, ctx, "INVOICE_CREDIT_APPLIED", "invoice", target.id, None,
                             {"amount": fmt(take), "from_invoice_id": src["invoice"].id, "transaction_id": t.id})
                refresh_status(db, ctx, src["invoice"])
    if done:
        db.expire(target)
    return done


def remove_credit(db: Session, ctx, i: Invoice, reason: str) -> int:
    """Register User: the credit applied to this invoice goes back to being the customer's credit (an overpayment on
    the invoice it came from), on the same deposits."""
    from ..schemas import AllocationIn
    inv.require_module(db, ctx)
    ctx.require("transaction.manage")
    reason = (reason or "").strip()
    if not reason:
        raise validation("Say why the credit is taken off.", "reason")
    by_txn: dict[int, list] = {}
    for link, a, t in _live_links(db, i.id):
        if link.credit_from_invoice_id:
            by_txn.setdefault(t.id, []).append((link, a, t))
    if not by_txn:
        raise conflict("NO_CREDIT", "No account credit is applied to this invoice.")
    back = 0
    for _tid, rows in by_txn.items():
        t = rows[0][2]
        fy = _deposit_fy(db, ctx.workspace_id, t.transaction_date)
        ap = Applied()
        ap.reason = f"Credit taken off invoice {docs.display_number(i)}: {reason}"[:500]
        ap.unlink = [link for link, _a, _t in rows]
        ids = {a.id for _l, a, _t in rows}
        per_src: dict[int, int] = {}
        for link, a, _t in rows:
            per_src[link.credit_from_invoice_id] = per_src.get(link.credit_from_invoice_id, 0) + a.amount_cents
        for x in t.live_allocations:
            if x.id in ids:
                continue
            ap.allocations.append(AllocationIn(id=x.id, budget_id=x.budget_id, entity_id=x.entity_id,
                                               invoice_number=x.invoice_number, invoice_date=x.invoice_date,
                                               description=x.description, amount=fmt(x.amount_cents), notes=x.notes,
                                               fiscal_year_id=x.budget.fiscal_year_id))
        ent = rows[0][1].entity_id
        for src_id, cents in per_src.items():
            src = db.get(Invoice, src_id)
            for gi, k in _invoice_allocations(db, src, figures(db, src)["paid"], 0, cents, fy, ent):
                ap.allocations.append(gi)
                ap.generated.add(id(gi))
                ap.links.append((gi, src, k))
            back += cents
        if not _system_update(db, ctx, t, ap):
            raise conflict("CREDIT_LOCKED", "The deposit holding this credit can't be changed (it may be in a Closed "
                           "Fiscal Year or voided).")
        for src_id in per_src:
            refresh_status(db, ctx, db.get(Invoice, src_id))
    audit.record(db, ctx, "INVOICE_CREDIT_REMOVED", "invoice", i.id, None, {"amount": fmt(back), "reason": reason})
    refresh_status(db, ctx, i)
    return back


# ------------------------------------------------------------------ link an existing deposit
def link(db: Session, ctx, i: Invoice, allocation_id: int, confirmations: list[str], extra: str | None = None,
         amount: str | None = None) -> InvoicePayment | None:
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
        return _link_moving(db, ctx, i, a, confirmations, extra, amount)
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


def _link_moving(db: Session, ctx, i: Invoice, a: TransactionAllocation, confirmations: list[str],
                 extra: str | None, amount: str | None) -> None:
    """2.4.0 (#533): a deposit line on an ordinary Income budget is moved onto the invoice's budgets and linked in one
    step (a register edit, Register User): the invoice's part becomes its splits; the rest of the line stays on its
    budget (BUDGET), or is an overpayment kept as credit (CREDIT) or refunded (REFUND)."""
    from ..schemas import AllocationIn, ApplyToInvoiceIn, TransactionUpdateIn
    from . import register as reg
    ctx.require("transaction.manage")
    t = a.transaction
    if a.budget.budget_type != "INCOME":
        raise AppError(422, "NOT_INCOME", "Only a deposit line on an Income budget can pay an invoice.")
    if linked_allocations(db, [a.id]):
        raise conflict("ALREADY_LINKED", "This deposit line is already linked to an invoice.")
    f = figures(db, i)
    try:
        part = parse_amount(amount, allow_zero=False) if amount else min(a.amount_cents, f["open"])
    except ValueError as e:
        raise validation(str(e), "amount") from None
    part = min(part, a.amount_cents)
    if part > f["open"]:
        raise AppError(422, "OVER_OPEN_BALANCE", f"{fmt(part)} is more than the invoice's open balance of "
                       f"{fmt(f['open'])}.")
    rows = []
    for x in t.live_allocations:
        ai = AllocationIn(id=x.id, budget_id=x.budget_id, entity_id=x.entity_id, invoice_number=x.invoice_number,
                          invoice_date=x.invoice_date, description=x.description, amount=fmt(x.amount_cents),
                          notes=x.notes, fiscal_year_id=x.budget.fiscal_year_id)
        if x.id == a.id:
            ai = ai.model_copy(update={"apply_to": [ApplyToInvoiceIn(invoice_id=i.id, amount=fmt(part))],
                                       "apply_extra": (extra or "BUDGET") if a.amount_cents > part else None,
                                       "apply_extra_invoice_id": i.id})
        rows.append(ai)
    reg.update(db, ctx, t, TransactionUpdateIn(allocations=rows, confirmations=confirmations))
    return None


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
    if p.kind == "OVERPAYMENT" and a.amount_cents > figures(db, i)["refundable"]:   # 2.4.0 (#534): moving credit
        raise conflict("PARTLY_REFUNDED", "Part of this credit was refunded; only what is left can be moved. Refund or "
                       "apply the rest instead.")
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
    """Deposit lines that could be linked: active, unlinked, on an Income budget (#533: an ordinary one is moved onto
    the invoice's budgets when linked), not in a closed year; the customer's first, then the newest."""
    from . import register as reg
    inv.require_module(db, ctx)
    ctx.require("invoice.link_payment")
    out = []
    q = (select(TransactionAllocation).join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
         .join(Budget, Budget.id == TransactionAllocation.budget_id)
         .where(RegisterTransaction.workspace_id == ctx.workspace_id, RegisterTransaction.status == "ACTIVE",
                RegisterTransaction.transaction_type == "DEPOSIT", TransactionAllocation.removed_at.is_(None),
                Budget.budget_type == "INCOME", Budget.is_budget_zero.is_(False))
         .order_by(RegisterTransaction.transaction_date.desc()).limit(400))
    linked = None
    for a in db.scalars(q):
        if linked is None:
            linked = set()
        if linked_allocations(db, [a.id]) or reg.is_closed_protected(db, a.transaction):
            continue
        e = db.get(Entity, a.entity_id or a.transaction.parent_entity_id) if (a.entity_id or a.transaction.parent_entity_id) else None
        out.append({"allocation_id": a.id, "transaction_id": a.transaction_id, "date": a.transaction.transaction_date.isoformat(),
                    "amount": fmt(a.amount_cents), "entity": e.display_name if e else None,
                    "budget": cat._budget_brief(db, a.budget_id), "description": a.description,
                    "moves": not a.budget.invoiced_income, "customer": bool(e and e.id == i.customer_entity_id)})
    out.sort(key=lambda r: (not r["customer"], r["moves"]))       # stable: newest first within each group
    return out[:200]
