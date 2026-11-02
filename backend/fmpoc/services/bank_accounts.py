"""Bank Accounts: encrypted numbers, masking, reveal, Primary, balances, closure (BR-035..044, BR-093)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

from sqlalchemy import case, func, select, update as sa_update
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, Warning_, conflict, not_found, require_confirmations, validation
from ..models import BankAccount, BankAccountBalance, Entity, RegisterTransaction, TransactionAllocation, utcnow
from ..money import fmt, parse_amount
from ..security import crypto
from .common import entity_brief, get_scoped

REGISTER_DEFAULT = {"CHECKING": True, "SAVINGS": True, "INVESTMENT": False}


def masked(a: BankAccount) -> str:
    return crypto.mask(a.account_number_visible_suffix)


def snapshot(a: BankAccount) -> dict:
    # Never the plaintext/ciphertext/fingerprint - masked representation only (BR-036/BR-103).
    return {"id": a.id, "account_name": a.account_name, "financial_institution_entity_id": a.financial_institution_entity_id,
            "account_type": a.account_type, "account_subtype": a.account_subtype, "account_number_masked": masked(a),
            "register_enabled": a.register_enabled, "is_primary": a.is_primary, "interest_rate": a.interest_rate,
            "opening_balance": fmt(a.opening_balance_cents), "opening_balance_date": a.opening_balance_date,
            "account_opened_date": a.account_opened_date,
            "manual_current_balance": fmt(a.manual_current_balance_cents), "status": a.status,
            "closed_date": a.closed_date, "close_reason": a.close_reason, "notes": a.notes}


def _register_sum(db: Session, a: BankAccount, *conds) -> int:
    signed = case((RegisterTransaction.transaction_type == "DEPOSIT", TransactionAllocation.amount_cents),
                  else_=-TransactionAllocation.amount_cents)
    q = (select(func.coalesce(func.sum(signed), 0))
         .select_from(RegisterTransaction)
         .join(TransactionAllocation, TransactionAllocation.transaction_id == RegisterTransaction.id)
         .where(RegisterTransaction.bank_account_id == a.id, RegisterTransaction.status == "ACTIVE",
                TransactionAllocation.removed_at.is_(None), *conds))
    return (a.opening_balance_cents or 0) + int(db.scalar(q) or 0)


def _opened(d: dt.date | None) -> dt.date | None:
    if d is not None and d > dt.date.today():
        raise validation("Account opened can't be in the future.", "account_opened_date")
    return d


def balance_on(db: Session, a: BankAccount, d: dt.date) -> tuple[int, dict | None]:
    """2.2.0 (#348): the (bank) balance on a date for a point-in-time comparison, with one rule everywhere:
    - before *Account opened*: $0 - the account really was opened later;
    - before any data (a register account before its Opening Balance Date, a non-register account before its first
      balance entry) and no *Account opened*: the account existed before PennyWarden, so the **earliest available
      data** is used - the balance on the Opening Balance Date / the first entry - instead of $0;
    - otherwise the balance on that date.
    Returns (cents, substitution): substitution is None, or {"date": the date of the data used} when the earliest data
    stood in for a date before it (shown as a marker or a note)."""
    if a.account_opened_date is not None and d < a.account_opened_date:
        return 0, None
    if not a.register_enabled:
        v = manual_as_of(db, a, d)
        if v is not None:
            return v, None
        first = db.scalar(select(BankAccountBalance).where(BankAccountBalance.bank_account_id == a.id,
                                                           BankAccountBalance.retired_at.is_(None))
                          .order_by(BankAccountBalance.as_of_date, BankAccountBalance.id).limit(1))
        if first is None:
            return a.manual_current_balance_cents or 0, None
        return first.balance_cents, {"date": first.as_of_date}
    start = register_start(a)
    if start is not None and d < start:       # the register's opening balance stands in for the earlier date
        return current_cents(db, a, d), {"date": start}
    return current_cents(db, a, d), None


def register_start(a: BankAccount) -> dt.date | None:
    """Where a register account's data starts: its Opening Balance Date, else the day it was added."""
    return a.opening_balance_date or (a.created_at.date() if a.created_at else None)


def manual_as_of(db: Session, a: BankAccount, as_of: dt.date) -> int | None:
    """1.7.3 (#88): a non-register account's balance on a date - the latest history entry on or before it (for the
    same date, the one entered last); None before the first entry. The balance carries forward between entries."""
    e = db.scalar(select(BankAccountBalance).where(BankAccountBalance.bank_account_id == a.id,
                                                   BankAccountBalance.retired_at.is_(None),     # 2.3.0 (#391)
                                                   BankAccountBalance.as_of_date <= as_of)
                  .order_by(BankAccountBalance.as_of_date.desc(), BankAccountBalance.id.desc()).limit(1))
    return e.balance_cents if e is not None else None


def _manual(db: Session, a: BankAccount, as_of: dt.date | None) -> int:
    if as_of is None:
        return a.manual_current_balance_cents or 0
    return manual_as_of(db, a, as_of) or 0


def available_cents(db: Session, a: BankAccount, as_of: dt.date | None = None) -> int:
    """1.7.2 (#56) Available Balance - everything written or deposited: opening balance + ACTIVE deposits - ACTIVE
    withdrawals with a Transaction Date on or before as_of, cleared or not (parent totals only, BR-047). Shown in the
    Register only; it is also the basis of the Register's running balance and of the Fiscal Year starting balance
    (BR-043). Non-register accounts have no clearing: the manually maintained balance."""
    if not a.register_enabled:
        return _manual(db, a, as_of)
    return _register_sum(db, a, *([RegisterTransaction.transaction_date <= as_of] if as_of is not None else []))


def current_cents(db: Session, a: BankAccount, as_of: dt.date | None = None) -> int:
    """1.7.2 (#56) Current Balance - the real bank balance: opening balance + ACTIVE transactions the bank has posted,
    i.e. with a Clear/Post Date (on or before as_of when given). Shown everywhere outside the Register.
    Non-register accounts: the manually maintained balance."""
    if not a.register_enabled:
        return _manual(db, a, as_of)
    cond = [RegisterTransaction.clear_date.is_not(None)]
    if as_of is not None:
        cond.append(RegisterTransaction.clear_date <= as_of)
    return _register_sum(db, a, *cond)


def outstanding(db: Session, a: BankAccount, as_of: dt.date) -> list[RegisterTransaction]:
    """1.7.2 (#56): the items that make up the difference between the bank (Current) and the Available balance on a
    date - ACTIVE transactions dated on or before it that had not cleared by then."""
    if not a.register_enabled:
        return []
    return list(db.scalars(select(RegisterTransaction).where(
        RegisterTransaction.bank_account_id == a.id, RegisterTransaction.status == "ACTIVE",
        RegisterTransaction.transaction_date <= as_of,
        (RegisterTransaction.clear_date.is_(None)) | (RegisterTransaction.clear_date > as_of))
        .order_by(RegisterTransaction.transaction_date, RegisterTransaction.id)))


def uncleared_count(db: Session, a: BankAccount) -> int:
    return db.scalar(select(func.count(RegisterTransaction.id)).where(
        RegisterTransaction.bank_account_id == a.id, RegisterTransaction.status == "ACTIVE",
        RegisterTransaction.clear_date.is_(None))) or 0


def has_transactions(db: Session, a: BankAccount) -> bool:
    return db.scalar(select(RegisterTransaction.id).where(RegisterTransaction.bank_account_id == a.id).limit(1)) is not None


# v1.5.0 CR-028: Bank Accounts page and dashboard show two groups (product owner: only checking and savings are
# "Checking & Savings"; money market, CDs, investments, cash and other are "Investments and Other").
GROUPS = [("CHECKING_SAVINGS", "Checking & Savings"), ("INVESTMENTS_OTHER", "Investments and Other")]
CHECKING_SAVINGS_TYPES = {"CHECKING", "SAVINGS"}


def group_of(account_type: str) -> str:
    return "CHECKING_SAVINGS" if account_type in CHECKING_SAVINGS_TYPES else "INVESTMENTS_OTHER"


GROUP_LABELS = dict(GROUPS)


def listing_order() -> tuple:
    """1.7.1 (#74): the order Budget Managers set - group by group (Checking & Savings first), then the stored
    position within the group. Used by the Bank Accounts page, the Dashboard and the Register account selector."""
    return (case((BankAccount.account_type.in_(sorted(CHECKING_SAVINGS_TYPES)), 0), else_=1),
            BankAccount.sort_order, BankAccount.id)


def _group_members(db: Session, ws_id: int, group: str) -> list[BankAccount]:
    types = BankAccount.account_type.in_(sorted(CHECKING_SAVINGS_TYPES))
    return list(db.scalars(select(BankAccount).where(BankAccount.workspace_id == ws_id,
                                                     types if group == "CHECKING_SAVINGS" else ~types)
                           .order_by(BankAccount.sort_order, BankAccount.id)))


def _end_of_group(db: Session, ws_id: int, account_type: str, exclude_id: int | None = None) -> int:
    """A new account (or one whose type moves it to the other group) goes to the end of its group."""
    return max((m.sort_order for m in _group_members(db, ws_id, group_of(account_type)) if m.id != exclude_id),
               default=0) + 1


def move(db: Session, ctx, a: BankAccount, direction: str) -> dict:
    """1.7.1 (#74): move an account one place up or down within its group. Positions in the group are renumbered
    1..n so they stay tidy. The Primary account is not pinned; it moves like any other account."""
    group = group_of(a.account_type)
    members = _group_members(db, ctx.workspace_id, group)
    i = next(n for n, m in enumerate(members) if m.id == a.id)
    j = i - 1 if direction == "up" else i + 1
    if j < 0 or j >= len(members):
        raise conflict("CANNOT_MOVE", f"The account is already {'first' if direction == 'up' else 'last'} in "
                                      f"{GROUP_LABELS[group]}.")
    before = [m.id for m in members]
    members[i], members[j] = members[j], members[i]
    for pos, m in enumerate(members, start=1):
        m.sort_order = pos
    db.flush()
    audit.record(db, ctx, "BANK_ACCOUNT_ORDER_CHANGED", "bank_account", a.id,
                 {"group": group, "position": i + 1, "order": before},
                 {"group": group, "position": j + 1, "order": [m.id for m in members]})
    return {"account": out(db, a), "group": group, "position": j + 1, "group_size": len(members)}


def out(db: Session, a: BankAccount) -> dict:
    bal = current_cents(db, a)  # 1.7.2 (#56): the bank balance (cleared only) everywhere outside the Register
    return {**snapshot(a), "opening_balance_date": a.opening_balance_date.isoformat() if a.opening_balance_date else None,
            "account_opened_date": a.account_opened_date.isoformat() if a.account_opened_date else None,
            "closed_date": a.closed_date.isoformat() if a.closed_date else None,
            "financial_institution": entity_brief(a.institution), "current_balance": fmt(bal),
            "label": f"{a.account_name} - {masked(a)}", "uncleared_count": uncleared_count(db, a),
            "has_transactions": has_transactions(db, a), "group": group_of(a.account_type),
            "sort_order": a.sort_order}


def _institution(db: Session, ctx, entity_id: int, current_id: int | None = None) -> Entity:
    e = db.get(Entity, entity_id)
    if e is None or e.workspace_id != ctx.workspace_id or e.is_system:
        raise validation("Financial Institution not found.", "financial_institution_entity_id")
    if not e.is_financial_institution:
        raise validation("The selected Entity is not flagged as a Financial Institution.", "financial_institution_entity_id")
    if not e.active and e.id != current_id:
        raise validation("The selected Financial Institution is inactive.", "financial_institution_entity_id")
    return e


def _rate(v: str | None) -> str | None:
    if v in (None, ""):
        return None
    try:
        d = Decimal(v)
    except InvalidOperation:
        raise validation("Interest rate must be a decimal percentage.", "interest_rate") from None
    if not d.is_finite() or d < 0 or d > 100 or d.as_tuple().exponent < -4:
        raise validation("Interest rate must be between 0 and 100 with at most 4 decimal places.", "interest_rate")
    return str(d)


def _set_number(db: Session, a: BankAccount, km, raw: str, exclude_id: int | None) -> None:
    try:
        norm = crypto.normalize_account_number(raw)
    except ValueError as e:
        raise validation(str(e), "account_number") from None
    fp = crypto.fingerprint(km, norm)
    q = select(BankAccount.id).where(BankAccount.workspace_id == a.workspace_id,
                                     BankAccount.account_number_fingerprint == fp)
    if exclude_id:
        q = q.where(BankAccount.id != exclude_id)
    if db.scalar(q):
        raise conflict("DUPLICATE_ACCOUNT_NUMBER", "A Bank Account with this account number already exists in the Workspace.")
    a.account_number_ciphertext = crypto.encrypt(km, norm)
    a.account_number_fingerprint = fp
    a.account_number_visible_suffix = crypto.visible_suffix(norm)


def _clear_primary(db: Session, ws_id: int, except_id: int | None) -> None:
    stmt = sa_update(BankAccount).where(BankAccount.workspace_id == ws_id, BankAccount.is_primary.is_(True))
    if except_id:
        stmt = stmt.where(BankAccount.id != except_id)
    db.execute(stmt.values(is_primary=False))


def create(db: Session, ctx, km, data) -> BankAccount:
    _institution(db, ctx, data.financial_institution_entity_id)
    reg = data.register_enabled if data.register_enabled is not None else REGISTER_DEFAULT.get(data.account_type, False)
    a = BankAccount(workspace_id=ctx.workspace_id, financial_institution_entity_id=data.financial_institution_entity_id,
                    account_name=data.account_name, account_type=data.account_type, account_subtype=data.account_subtype,
                    register_enabled=reg, interest_rate=_rate(data.interest_rate), notes=data.notes, status="ACTIVE",
                    created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id,
                    sort_order=_end_of_group(db, ctx.workspace_id, data.account_type))
    _set_number(db, a, km, data.account_number, None)
    a.account_opened_date = _opened(data.account_opened_date)
    try:
        if reg:
            if data.current_balance is not None:
                raise validation("Register-enabled balances are derived; supply an Opening Balance instead.", "current_balance")
            a.opening_balance_cents = parse_amount(data.opening_balance or "0", allow_negative=True)
            a.opening_balance_date = data.opening_balance_date or dt.date.today()
        else:
            if data.opening_balance is not None:
                a.opening_balance_cents = parse_amount(data.opening_balance, allow_negative=True)
                a.opening_balance_date = data.opening_balance_date
            a.manual_current_balance_cents = parse_amount(data.current_balance or data.opening_balance or "0",
                                                          allow_negative=True)
    except ValueError as e:
        raise validation(str(e), "opening_balance") from None
    if data.is_primary:
        if not reg:
            raise validation("Only a register-enabled account may be Primary.", "is_primary")
        _clear_primary(db, ctx.workspace_id, None)
        a.is_primary = True
    db.add(a)
    db.flush()
    if not reg:  # 1.7.3 (#88): the balance entered at creation is the first history entry
        _add_entry(db, ctx, a, dt.date.today(), a.manual_current_balance_cents or 0, None, "OPENING")
    audit.record(db, ctx, "BANK_ACCOUNT_CREATED", "bank_account", a.id, None, snapshot(a))
    return a


def _add_entry(db: Session, ctx, a: BankAccount, as_of: dt.date, cents: int, reason: str | None,
               source: str = "UPDATE") -> BankAccountBalance:
    e = BankAccountBalance(workspace_id=a.workspace_id, bank_account_id=a.id, as_of_date=as_of, balance_cents=cents,
                           reason=reason, source=source, entered_at=utcnow(), entered_by_user_id=ctx.user.id)
    db.add(e)
    db.flush()
    _recompute(db, a)
    return e


def _recompute(db: Session, a: BankAccount) -> None:
    """The current balance = the counted (not retired) entry with the latest date (2.3.0, #391: also after a
    correction or a retirement, in the same transaction)."""
    latest = db.scalar(select(BankAccountBalance).where(BankAccountBalance.bank_account_id == a.id,
                                                        BankAccountBalance.retired_at.is_(None))
                       .order_by(BankAccountBalance.as_of_date.desc(), BankAccountBalance.id.desc()).limit(1))
    a.manual_current_balance_cents = latest.balance_cents if latest is not None else 0


def first_fiscal_year_start(db: Session, ws_id: int) -> dt.date | None:
    from ..models import FiscalYear
    return db.scalar(select(func.min(FiscalYear.start_date)).where(FiscalYear.workspace_id == ws_id))


def balance_history(db: Session, a: BankAccount) -> list[dict]:
    """1.7.3 (#88): newest first, each with the change from the entry before it (by date, then entry order).
    2.3.0 (#391): only counted entries make the change; retired entries follow, marked `retired` (newest first);
    `entered` marks an entry dated before the first Fiscal Year in PennyWarden; `corrected` carries the last
    correction (who, when, why, and the values it replaced)."""
    from ..models import User
    rows = list(db.scalars(select(BankAccountBalance).where(BankAccountBalance.bank_account_id == a.id)
                           .order_by(BankAccountBalance.as_of_date, BankAccountBalance.id)))
    ids = {r.entered_by_user_id for r in rows} | {r.corrected_by_user_id for r in rows} | {r.retired_by_user_id for r in rows}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids - {None})))}
    name = lambda uid: (users[uid].display_name or users[uid].username) if uid in users else None   # noqa: E731
    first = first_fiscal_year_start(db, a.workspace_id)

    def one(r: BankAccountBalance, change) -> dict:
        return {"id": r.id, "as_of_date": r.as_of_date.isoformat(), "balance": fmt(r.balance_cents),
                "change": change, "reason": r.reason, "source": r.source, "entered_at": r.entered_at.isoformat() + "Z",
                "entered_by": name(r.entered_by_user_id),
                "entered": first is None or r.as_of_date < first,
                "corrected": None if r.corrected_at is None else {
                    "at": r.corrected_at.isoformat() + "Z", "by": name(r.corrected_by_user_id), "reason": r.correct_reason,
                    "previous_balance": fmt(r.previous_balance_cents),
                    "previous_as_of_date": r.previous_as_of_date.isoformat() if r.previous_as_of_date else None},
                "retired": None if r.retired_at is None else {
                    "at": r.retired_at.isoformat() + "Z", "by": name(r.retired_by_user_id), "reason": r.retire_reason}}
    out, prev = [], None
    for r in rows:
        if r.retired_at is not None:
            continue
        out.append(one(r, fmt(r.balance_cents - prev) if prev is not None else None))
        prev = r.balance_cents
    retired = [one(r, None) for r in rows if r.retired_at is not None]
    return list(reversed(out)) + list(reversed(retired))


def _require_active(a: BankAccount) -> None:
    if a.status != "ACTIVE":
        raise conflict("ACCOUNT_CLOSED", "The Bank Account is closed.")


def update(db: Session, ctx, km, a: BankAccount, data) -> BankAccount:
    _require_active(a)
    before = snapshot(a)
    f = data.model_fields_set
    txns = has_transactions(db, a)
    if "account_name" in f and data.account_name:
        a.account_name = data.account_name
    if "financial_institution_entity_id" in f and data.financial_institution_entity_id is not None:
        _institution(db, ctx, data.financial_institution_entity_id, a.financial_institution_entity_id)
        a.financial_institution_entity_id = data.financial_institution_entity_id
    if "account_type" in f and data.account_type:
        if group_of(data.account_type) != group_of(a.account_type):  # 1.7.1 (#74): end of the new group
            a.sort_order = _end_of_group(db, ctx.workspace_id, data.account_type, a.id)
        a.account_type = data.account_type
    if "account_subtype" in f:
        a.account_subtype = data.account_subtype
    if "account_number" in f and data.account_number:
        _set_number(db, a, km, data.account_number, a.id)
    if "interest_rate" in f:
        a.interest_rate = _rate(data.interest_rate)
    if "notes" in f:
        a.notes = data.notes
    if "account_opened_date" in f:     # 2.2.0 (#348)
        a.account_opened_date = _opened(data.account_opened_date)
    if "register_enabled" in f and data.register_enabled is not None and data.register_enabled != a.register_enabled:
        if txns:
            raise conflict("HAS_TRANSACTIONS", "Register Enabled cannot change once Register transactions exist.")
        if data.register_enabled:
            a.opening_balance_cents = a.manual_current_balance_cents or 0
            a.opening_balance_date = a.opening_balance_date or dt.date.today()
        else:
            a.manual_current_balance_cents = a.opening_balance_cents or 0
            a.is_primary = False
            a.register_enabled = False
            _add_entry(db, ctx, a, dt.date.today(), a.manual_current_balance_cents, "No longer register-enabled")
        a.register_enabled = data.register_enabled
    if ("opening_balance" in f and data.opening_balance is not None) or ("opening_balance_date" in f and data.opening_balance_date):
        if txns:
            # Prevents manually overriding the calculated register balance (BR-093).
            raise conflict("HAS_TRANSACTIONS", "Opening Balance cannot change once Register transactions exist.")
        if "opening_balance" in f and data.opening_balance is not None:
            try:
                a.opening_balance_cents = parse_amount(data.opening_balance, allow_negative=True)
            except ValueError as e:
                raise validation(str(e), "opening_balance") from None
        if "opening_balance_date" in f and data.opening_balance_date:
            a.opening_balance_date = data.opening_balance_date
    a.updated_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "BANK_ACCOUNT_UPDATED", "bank_account", a.id, before, snapshot(a))
    return a


def set_primary(db: Session, ctx, a: BankAccount) -> BankAccount:
    """BR-039: atomically clears the prior Primary."""
    _require_active(a)
    if not a.register_enabled:
        raise validation("Only a register-enabled active account may be Primary.", "is_primary")
    prior = db.scalar(select(BankAccount).where(BankAccount.workspace_id == ctx.workspace_id,
                                                BankAccount.is_primary.is_(True), BankAccount.id != a.id))
    _clear_primary(db, ctx.workspace_id, a.id)
    a.is_primary = True
    db.flush()
    audit.record(db, ctx, "BANK_ACCOUNT_PRIMARY_SET", "bank_account", a.id,
                 {"primary_account_id": prior.id if prior else None}, {"primary_account_id": a.id})
    return a


# ------------------------------------------------------------------ 2.3.0 (#391): the rules for a balance date
CLOSED_YEAR_PERMISSION = "bank_account.closed_year"      # Budget Admins (always also Budget Managers)
CLOSED_YEAR_EVENT = "BANK_ACCOUNT_BALANCE_CHANGED_AFTER_CLOSE"


def _check_date(db: Session, ctx, a: BankAccount, d: dt.date, field: str = "as_of_date") -> list:
    """Open years: as before. Before the first Fiscal Year in PennyWarden: allowed, even before the account's opening
    balance date (backfilling history). Inside a Closed Fiscal Year: refused for Budget Managers; Budget Admins may,
    with a confirmation and a reason (checked by the caller). Returns the Closed Fiscal Years the date is in."""
    if d > dt.date.today():
        raise validation("The balance date cannot be in the future.", field)
    first = first_fiscal_year_start(db, a.workspace_id)
    before_pw = first is None or d < first
    if a.opening_balance_date and d < a.opening_balance_date and not before_pw:
        raise validation("The balance date cannot be before the account's opening balance date.", field)
    from .common import covering_fiscal_years
    closed = [f for f in covering_fiscal_years(db, a.workspace_id, d) if f.status == "CLOSED"]
    if closed and not ctx.has(CLOSED_YEAR_PERMISSION):
        raise conflict("FISCAL_YEAR_CLOSED", f"{closed[0].display_name} is closed; its balances cannot change.")
    return closed


def _closed_year_gate(closed: list, reason: str | None, confirmations) -> None:
    if not closed:
        return
    names = ", ".join(f.display_name for f in closed)
    if not (reason or "").strip():
        raise validation(f"{names} is closed: a reason is required to change a balance in it.", "reason")
    require_confirmations([Warning_("CLOSED_FISCAL_YEAR",
                                    f"{names} is closed. It was closed with the old balance; this change will be "
                                    "recorded and shown as 'Balance changed after close' on the Fiscal Year and its "
                                    "Close report.")], confirmations)


def _entry_snapshot(e: BankAccountBalance) -> dict:
    return {"balance_entry_id": e.id, "as_of_date": e.as_of_date.isoformat(), "balance": fmt(e.balance_cents),
            "retired": e.retired_at is not None}


def _record_closed(db: Session, ctx, a: BankAccount, closed: list, e: BankAccountBalance, action: str,
                   before: dict | None, after: dict | None, reason: str) -> None:
    import json
    from ..models import FiscalYearBalanceChange
    for fy in closed:
        db.add(FiscalYearBalanceChange(workspace_id=a.workspace_id, fiscal_year_id=fy.id, bank_account_id=a.id,
                                       balance_entry_id=e.id, action=action, reason=reason.strip(),
                                       before_json=json.dumps(before) if before else None,
                                       after_json=json.dumps(after) if after else None,
                                       changed_at=utcnow(), changed_by_user_id=ctx.user.id))
    db.flush()


def _audit_balance(db: Session, ctx, a: BankAccount, action: str, closed: list, before: dict | None, after: dict) -> None:
    """A change inside a Closed Fiscal Year is its own audit event, flagged with the year (#391)."""
    if closed:
        after = {**after, "action": action, "closed_fiscal_years": [f.display_name for f in closed]}
        audit.record(db, ctx, CLOSED_YEAR_EVENT, "bank_account", a.id, before, after, category="SECURITY")
    else:
        audit.record(db, ctx, action, "bank_account", a.id, before, after)


def update_manual_balance(db: Session, ctx, a: BankAccount, value: str, reason: str | None,
                          as_of: dt.date | None = None, confirmations=None) -> BankAccount:
    """1.7.3 (#88): every update adds a dated history entry; as_of defaults to today, may be earlier (e.g. a
    month-end statement), never in the future. 2.3.0 (#391): before the first Fiscal Year it may also precede the
    opening balance date; inside a Closed Fiscal Year only a Budget Admin, confirmed, with a reason."""
    _require_active(a)
    if a.register_enabled:
        raise conflict("REGISTER_BALANCE_DERIVED",
                       "Register-enabled balances are derived from Register activity and cannot be set manually.")
    as_of = as_of or dt.date.today()
    closed = _check_date(db, ctx, a, as_of)
    try:
        cents = parse_amount(value, allow_negative=True)
    except ValueError as e:
        raise validation(str(e), "current_balance") from None
    _closed_year_gate(closed, reason, confirmations)
    before = snapshot(a)
    entry = _add_entry(db, ctx, a, as_of, cents, reason)
    a.updated_by_user_id = ctx.user.id
    db.flush()
    after = {**snapshot(a), "reason": reason, "as_of_date": as_of.isoformat(), "entry_balance": fmt(cents),
             "balance_entry_id": entry.id}
    if closed:
        _record_closed(db, ctx, a, closed, entry, "ADD", None, _entry_snapshot(entry), reason)
    _audit_balance(db, ctx, a, "BANK_ACCOUNT_BALANCE_UPDATED", closed, before, after)
    return a


def _entry(db: Session, a: BankAccount, entry_id: int) -> BankAccountBalance:
    e = db.get(BankAccountBalance, entry_id) if isinstance(entry_id, int) else None
    if e is None or e.bank_account_id != a.id or e.workspace_id != a.workspace_id:
        raise not_found("Balance entry")
    if e.retired_at is not None:
        raise conflict("ENTRY_RETIRED", "This balance entry is retired.")
    return e


def _need_reason(reason: str | None) -> str:
    r = (reason or "").strip()
    if not r:
        raise validation("A reason is required.", "reason")
    return r


def correct_balance(db: Session, ctx, a: BankAccount, entry_id: int, value: str | None, as_of: dt.date | None,
                    reason: str | None, confirmations=None) -> BankAccountBalance:
    """2.3.0 (#391): Correct an entry's amount and/or "as of" date, with a reason. Both the old and the new date follow
    the date rules (a closed year on either side needs a Budget Admin). Audited before/after; the current balance is
    recalculated in the same transaction."""
    _require_active(a)
    if a.register_enabled:
        raise conflict("REGISTER_BALANCE_DERIVED", "A register-enabled account has no balance history.")
    e = _entry(db, a, entry_id)
    why = _need_reason(reason)
    try:
        cents = e.balance_cents if value is None else parse_amount(value, allow_negative=True)
    except ValueError as x:
        raise validation(str(x), "balance") from None
    new_date = as_of or e.as_of_date
    if (cents, new_date) == (e.balance_cents, e.as_of_date):
        raise validation("Nothing to correct: the amount and the date are unchanged.", "balance")
    closed = {f.id: f for f in _check_date(db, ctx, a, e.as_of_date)}
    closed.update({f.id: f for f in _check_date(db, ctx, a, new_date)})
    closed_l = sorted(closed.values(), key=lambda f: f.start_date)
    _closed_year_gate(closed_l, why, confirmations)
    before_acct, before_e = snapshot(a), _entry_snapshot(e)
    e.previous_balance_cents, e.previous_as_of_date = e.balance_cents, e.as_of_date
    e.balance_cents, e.as_of_date = cents, new_date
    e.corrected_at, e.corrected_by_user_id, e.correct_reason = utcnow(), ctx.user.id, why
    db.flush()
    _recompute(db, a)
    a.updated_by_user_id = ctx.user.id
    db.flush()
    if closed_l:
        _record_closed(db, ctx, a, closed_l, e, "CORRECT", before_e, _entry_snapshot(e), why)
    _audit_balance(db, ctx, a, "BANK_ACCOUNT_BALANCE_CORRECTED", closed_l, {**before_acct, "entry": before_e},
                   {**snapshot(a), "entry": _entry_snapshot(e), "reason": why})
    return e


def retire_balance(db: Session, ctx, a: BankAccount, entry_id: int, reason: str | None,
                   confirmations=None) -> BankAccountBalance:
    """2.3.0 (#391): Retire a wrong entry, with a reason: it no longer counts and stays listed as retired (never
    deleted, BR-001). The account's only counted entry can't be retired - correct it instead."""
    _require_active(a)
    if a.register_enabled:
        raise conflict("REGISTER_BALANCE_DERIVED", "A register-enabled account has no balance history.")
    e = _entry(db, a, entry_id)
    why = _need_reason(reason)
    counted = db.scalar(select(func.count()).select_from(BankAccountBalance).where(
        BankAccountBalance.bank_account_id == a.id, BankAccountBalance.retired_at.is_(None)))
    if counted <= 1:
        raise conflict("LAST_BALANCE_ENTRY", "This is the account's only balance entry; correct it instead.")
    closed = _check_date(db, ctx, a, e.as_of_date)
    _closed_year_gate(closed, why, confirmations)
    before_acct, before_e = snapshot(a), _entry_snapshot(e)
    e.retired_at, e.retired_by_user_id, e.retire_reason = utcnow(), ctx.user.id, why
    db.flush()
    _recompute(db, a)
    a.updated_by_user_id = ctx.user.id
    db.flush()
    if closed:
        _record_closed(db, ctx, a, closed, e, "RETIRE", before_e, _entry_snapshot(e), why)
    _audit_balance(db, ctx, a, "BANK_ACCOUNT_BALANCE_RETIRED", closed, {**before_acct, "entry": before_e},
                   {**snapshot(a), "entry": _entry_snapshot(e), "reason": why})
    return e


def changes_after_close(db: Session, fy) -> list[dict]:
    """2.3.0 (#391): "Balance changed after close" - every balance change recorded in this Closed Fiscal Year."""
    import json
    from ..models import FiscalYearBalanceChange, User
    rows = list(db.scalars(select(FiscalYearBalanceChange).where(FiscalYearBalanceChange.fiscal_year_id == fy.id)
                           .order_by(FiscalYearBalanceChange.changed_at, FiscalYearBalanceChange.id)))
    if not rows:
        return []
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r.changed_by_user_id for r in rows} - {None})))}
    accts = {x.id: x for x in db.scalars(select(BankAccount).where(BankAccount.id.in_({r.bank_account_id for r in rows})))}
    out = []
    for r in rows:
        u, acct = users.get(r.changed_by_user_id), accts.get(r.bank_account_id)
        out.append({"id": r.id, "changed_at": r.changed_at.isoformat() + "Z",
                    "changed_by": (u.display_name or u.username) if u else None,
                    "account": f"{acct.account_name} - {masked(acct)}" if acct else None, "action": r.action,
                    "before": json.loads(r.before_json) if r.before_json else None,
                    "after": json.loads(r.after_json) if r.after_json else None, "reason": r.reason})
    return out


def close(db: Session, ctx, a: BankAccount, reason: str, closed_date: dt.date | None) -> BankAccount:
    """BR-040/041/093: no uncleared active transactions and balance exactly 0.00."""
    _require_active(a)
    blockers = []
    n = uncleared_count(db, a)
    if n:
        blockers.append({"code": "UNCLEARED_TRANSACTIONS", "message": f"{n} uncleared transaction(s) remain."})
    bal = current_cents(db, a)  # with no uncleared transactions Current and Available are the same
    if bal != 0:
        blockers.append({"code": "NON_ZERO_BALANCE", "message": f"Current balance is {fmt(bal)}; it must be exactly 0.00."})
    if blockers:
        raise AppError(409, "ACCOUNT_CLOSURE_BLOCKED", "The Bank Account cannot be closed.", blockers=blockers)
    before = snapshot(a)
    a.status = "CLOSED"
    a.is_primary = False
    a.closed_date = closed_date or dt.date.today()
    a.close_reason = reason
    a.updated_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "BANK_ACCOUNT_CLOSED", "bank_account", a.id, before, snapshot(a))
    return a


def reveal(db: Session, ctx, km, a: BankAccount) -> str:
    """BR-038: audited without writing the revealed number anywhere."""
    value = crypto.decrypt(km, a.account_number_ciphertext)
    audit.record(db, ctx, "ACCOUNT_NUMBER_REVEALED", "bank_account", a.id, None,
                 {"account_number_masked": masked(a)}, category="SECURITY")
    return value


def get(db: Session, ctx, account_id: int) -> BankAccount:
    return get_scoped(db, BankAccount, account_id, ctx, "Bank Account")
