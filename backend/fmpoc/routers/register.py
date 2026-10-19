from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..errors import AppError
from ..models import BankAccount, Budget, FiscalYear, FiscalYearReview, RegisterTransaction, TransactionAllocation
from ..schemas import (CheckAckIn, NoteIn, ReasonIn, ReviewResolveIn, TransactionCreateIn, TransactionUpdateIn, TransferIn,
                       VoidCheckNumberIn, VoidDateIn, VoidIn)
from ..services import bank_accounts as bank_svc
from ..services import idempotency
from ..services import register as svc
from ..services.common import get_scoped

router = APIRouter(prefix="/api", tags=["register"])


@router.get("/register")
def register_view(
    bank_account_id: int | None = None,
    fiscal_year_id: int | None = None,
    transaction_type: Literal["DEPOSIT", "WITHDRAWAL"] | None = None,
    status: Literal["cleared", "uncleared", "void", "active", "deleted"] | None = None,  # deleted: Auditors (1.7.3)
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    search: str | None = Query(None, max_length=200),
    # 1.6.7; 2.1.0 (#258): yes | missing (what the documentation review warns about) | marked; "no" = missing
    attachments: Literal["yes", "missing", "marked", "no"] | None = None,
    budget_id: int | None = None,  # 1.7.3 (#104): only transactions with an allocation to this budget (or its sub-budgets)
    sort: Literal["transaction_date", "entry_timestamp", "amount", "check_number", "clear_date"] = "transaction_date",
    direction: Literal["asc", "desc"] = "asc",
    db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view")),
):
    if status == "deleted" and "AUDITOR" not in ctx.roles:  # 1.7.3 (#53): only Auditors list deleted transactions
        raise AppError(422, "VALIDATION_ERROR", "The request is invalid.",
                       errors=[{"field": "status", "message": "Unknown status filter."}])
    if bank_account_id is None:  # default: Primary register-enabled account
        acct = db.scalar(select(BankAccount).where(BankAccount.workspace_id == ctx.workspace_id,
                                                   BankAccount.is_primary.is_(True)))
        if acct is None:
            acct = db.scalar(select(BankAccount).where(BankAccount.workspace_id == ctx.workspace_id,
                                                       BankAccount.register_enabled.is_(True))
                             .order_by(BankAccount.status, *bank_svc.listing_order()))
        if acct is None:
            return {"bank_account": None, "transactions": []}
    else:
        acct = get_scoped(db, BankAccount, bank_account_id, ctx, "Bank Account")
    if not acct.register_enabled:
        raise AppError(422, "NOT_REGISTER_ENABLED", "The Bank Account is not register-enabled.")
    fy = get_scoped(db, FiscalYear, fiscal_year_id, ctx, "Fiscal Year") if fiscal_year_id else None
    budget = get_scoped(db, Budget, budget_id, ctx, "Budget") if budget_id else None
    return svc.register_view(db, ctx, acct, fiscal_year=fy, txn_type=transaction_type, status=status,
                             date_from=date_from, date_to=date_to, search=search, sort=sort, direction=direction,
                             attachments=attachments, budget=budget, include_deleted="AUDITOR" in ctx.roles)


@router.get("/transactions/{txn_id}")
def get_txn(txn_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    return svc.out(db, svc.get(db, ctx, txn_id))


@router.post("/transactions", status_code=201)
def create_txn(body: TransactionCreateIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("transaction.manage"))):
    replay = idempotency.claim(db, ctx, body.request_key, "transaction")
    if replay:  # v1.3 CR-011: repeated submit of the same form - return the transaction already created
        return svc.out(db, svc.get(db, ctx, replay[0]))
    t = svc.create(db, ctx, body)
    idempotency.complete(db, ctx, body.request_key, [t.id])
    db.commit()
    return svc.out(db, t)


@router.post("/transfers", status_code=201)
def create_transfer(body: TransferIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("transaction.manage"))):
    from ..services import transfers
    replay = idempotency.claim(db, ctx, body.request_key, "transfer")
    if replay:
        return {"withdrawal": svc.out(db, svc.get(db, ctx, replay[0])), "deposit": svc.out(db, svc.get(db, ctx, replay[1]))}
    legs = transfers.create(db, ctx, body)
    idempotency.complete(db, ctx, body.request_key, [legs[0].id, legs[1].id])
    db.commit()
    return {"withdrawal": svc.out(db, legs[0]), "deposit": svc.out(db, legs[1])}


@router.patch("/transactions/{txn_id}")
def update_txn(txn_id: int, body: TransactionUpdateIn, db: Session = Depends(get_db),
               ctx: Ctx = Depends(require("transaction.manage"))):
    t = svc.update(db, ctx, svc.get(db, ctx, txn_id), body)
    db.commit()
    return svc.out(db, t)


@router.post("/transactions/{txn_id}/void")
def void_txn(txn_id: int, body: VoidIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("transaction.manage"))):
    t = svc.void(db, ctx, svc.get(db, ctx, txn_id), body.reason, body.confirm_irreversible)
    db.commit()
    return svc.out(db, t)


@router.post("/transactions/{txn_id}/delete")
def delete_txn(txn_id: int, body: ReasonIn, db: Session = Depends(get_db),
               ctx: Ctx = Depends(require("transaction.delete"))):
    """1.7.3 (#53): Register Admin - an uncleared transaction (both legs of a transfer) gets the status Deleted."""
    t = svc.delete(db, ctx, svc.get(db, ctx, txn_id), body.reason)
    db.commit()
    return {"id": t.id, "status": t.status}


@router.post("/transactions/{txn_id}/void-date")
def correct_void_date(txn_id: int, body: VoidDateIn, db: Session = Depends(get_db),
                      ctx: Ctx = Depends(require("transaction.manage"))):
    t = svc.correct_void_date(db, ctx, svc.get(db, ctx, txn_id), body.transaction_date, body.fiscal_year_id, body.reason)
    db.commit()
    return svc.out(db, t)


@router.post("/transactions/{txn_id}/void-check-number")
def correct_void_check_number(txn_id: int, body: VoidCheckNumberIn, db: Session = Depends(get_db),
                              ctx: Ctx = Depends(require("transaction.manage"))):
    t = svc.correct_void_check_number(db, ctx, svc.get(db, ctx, txn_id), body.check_number, body.reason)
    db.commit()
    return svc.out(db, t)


@router.post("/transactions/{txn_id}/notes")
def add_note(txn_id: int, body: NoteIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("transaction.manage"))):
    t = svc.add_note(db, ctx, svc.get(db, ctx, txn_id), body.note)
    db.commit()
    return svc.out(db, t)


@router.get("/check-review")
def check_review(bank_account_id: int | None = None, db: Session = Depends(get_db),
                 ctx: Ctx = Depends(require("financial.view"))):
    """v1.3 CR-012: possibly missing check numbers and (pre-v1.3) repeated check numbers."""
    from ..services import checks
    if bank_account_id is not None:
        get_scoped(db, BankAccount, bank_account_id, ctx, "Bank Account")
    return checks.review(db, ctx.workspace_id, bank_account_id)


@router.post("/check-review/acknowledge", status_code=201)
def acknowledge_checks(body: CheckAckIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("transaction.manage"))):
    from ..services import checks
    a = checks.acknowledge(db, ctx, body.bank_account_id, body.first_number, body.last_number, body.note)
    db.commit()
    return {"id": a.id, "bank_account_id": a.bank_account_id, "first_number": a.first_number,
            "last_number": a.last_number, "note": a.note}


@router.get("/fiscal-year-reviews")
def list_reviews(status: Literal["PENDING", "REVIEWED", "REASSIGNED", "all"] = "PENDING",
                 fiscal_year_id: int | None = None,
                 db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    q = (select(FiscalYearReview)
         .join(TransactionAllocation, TransactionAllocation.id == FiscalYearReview.transaction_allocation_id)
         .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
         .where(FiscalYearReview.workspace_id == ctx.workspace_id))
    if status != "all":
        q = q.where(FiscalYearReview.status == status)
    if status == "PENDING":
        q = q.where(RegisterTransaction.status == "ACTIVE", TransactionAllocation.removed_at.is_(None))
    items = [svc.review_out(db, r) for r in db.scalars(q.order_by(FiscalYearReview.id))]
    if fiscal_year_id:
        items = [i for i in items if i["budget"]["fiscal_year"]["id"] == fiscal_year_id
                 or (i["natural_fiscal_year"] or {}).get("id") == fiscal_year_id]
    return items


@router.post("/fiscal-year-reviews/{review_id}/confirm")
def confirm_review(review_id: int, body: ReviewResolveIn, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("review.resolve"))):
    r = svc.resolve_review(db, ctx, svc.get_review(db, ctx, review_id), body.note)
    db.commit()
    return svc.review_out(db, r)
