from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..errors import AppError
from ..models import BankAccount
from ..schemas import (BalanceCorrectIn, BalanceRetireIn, BankAccountCreateIn, BankAccountUpdateIn, CloseAccountIn,
                       ManualBalanceIn, MoveAccountIn)
from ..services import bank_accounts as svc

router = APIRouter(prefix="/api/bank-accounts", tags=["bank-accounts"])


def _key(request: Request):
    km = request.app.state.key
    if km is None:
        raise AppError(503, "KEY_UNAVAILABLE", "The portable encryption key is not available.")
    return km


@router.get("")
def list_accounts(include_closed: bool = True, db: Session = Depends(get_db), ctx: Ctx = Depends(require("register.view"))):
    q = select(BankAccount).where(BankAccount.workspace_id == ctx.workspace_id)
    if not include_closed:
        q = q.where(BankAccount.status == "ACTIVE")
    return [svc.out(db, a) for a in db.scalars(q.order_by(*svc.listing_order()))]


@router.get("/{account_id}")
def get_account(account_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("register.view"))):
    return svc.out(db, svc.get(db, ctx, account_id))


@router.post("", status_code=201)
def create(body: BankAccountCreateIn, request: Request, db: Session = Depends(get_db),
           ctx: Ctx = Depends(require("bank_account.manage"))):
    a = svc.create(db, ctx, _key(request), body)
    db.commit()
    return svc.out(db, a)


@router.patch("/{account_id}")
def update(account_id: int, body: BankAccountUpdateIn, request: Request, db: Session = Depends(get_db),
           ctx: Ctx = Depends(require("bank_account.manage"))):
    a = svc.update(db, ctx, _key(request), svc.get(db, ctx, account_id), body)
    db.commit()
    return svc.out(db, a)


@router.post("/{account_id}/set-primary")
def set_primary(account_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("bank_account.manage"))):
    a = svc.set_primary(db, ctx, svc.get(db, ctx, account_id))
    db.commit()
    return svc.out(db, a)


@router.post("/{account_id}/move")
def move(account_id: int, body: MoveAccountIn, db: Session = Depends(get_db),
         ctx: Ctx = Depends(require("bank_account.manage"))):
    """1.7.1 (#74): Budget Managers set the order of the accounts within each group."""
    r = svc.move(db, ctx, svc.get(db, ctx, account_id), body.direction)
    db.commit()
    return r


@router.post("/{account_id}/balance")
def manual_balance(account_id: int, body: ManualBalanceIn, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("bank_account.manage"))):
    a = svc.update_manual_balance(db, ctx, svc.get(db, ctx, account_id), body.current_balance, body.reason,
                                  body.as_of_date, body.confirmations)
    db.commit()
    return svc.out(db, a)


@router.post("/{account_id}/balance-history/{entry_id}/correct")
def correct_balance(account_id: int, entry_id: int, body: BalanceCorrectIn, db: Session = Depends(get_db),
                    ctx: Ctx = Depends(require("bank_account.manage"))):
    """2.3.0 (#391): correct a balance entry's amount and/or date (reason required)."""
    a = svc.get(db, ctx, account_id)
    svc.correct_balance(db, ctx, a, entry_id, body.balance, body.as_of_date, body.reason, body.confirmations)
    db.commit()
    return {"account": svc.out(db, a), "history": svc.balance_history(db, a)}


@router.post("/{account_id}/balance-history/{entry_id}/retire")
def retire_balance(account_id: int, entry_id: int, body: BalanceRetireIn, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("bank_account.manage"))):
    """2.3.0 (#391): retire a wrong balance entry (reason required); it stays listed as retired."""
    a = svc.get(db, ctx, account_id)
    svc.retire_balance(db, ctx, a, entry_id, body.reason, body.confirmations)
    db.commit()
    return {"account": svc.out(db, a), "history": svc.balance_history(db, a)}


@router.get("/{account_id}/balance-history")
def balance_history(account_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    """1.7.3 (#88): dated balance entries of a non-register account, newest first."""
    a = svc.get(db, ctx, account_id)
    if a.register_enabled:
        raise AppError(422, "REGISTER_ENABLED", "A register-enabled account's balance comes from its Register.")
    return svc.balance_history(db, a)


@router.post("/{account_id}/close")
def close(account_id: int, body: CloseAccountIn, db: Session = Depends(get_db),
          ctx: Ctx = Depends(require("bank_account.manage"))):
    a = svc.close(db, ctx, svc.get(db, ctx, account_id), body.reason, body.closed_date)
    db.commit()
    return svc.out(db, a)


@router.post("/{account_id}/reveal")
def reveal(account_id: int, request: Request, db: Session = Depends(get_db),
           ctx: Ctx = Depends(require("bank_account.reveal"))):
    value = svc.reveal(db, ctx, _key(request), svc.get(db, ctx, account_id))
    db.commit()
    return {"account_number": value}
