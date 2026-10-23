"""v1.3 check-number rules.

CR-011: a check number can be used only once per bank account. Every record keeps its number reserved - active
transactions, VOID transactions and zero-dollar VOID records - because a voided check (lost, spoiled) is never
reused. 2.1.0 (#289): a **deleted** transaction (an entry made by mistake) releases its number - it keeps it in its
own data for the Auditors, but no longer holds it, and the missing-check review ignores it. A number entered by mistake is released by correcting the record's check number (also allowed on VOID
records, audited). Numeric check numbers compare without leading zeros ("0105" == "105"); others compare
case-insensitively.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import conflict
from ..models import RegisterTransaction


def check_key(number: str | None) -> str | None:
    s = (number or "").strip()
    if not s:
        return None
    return str(int(s)) if s.isdigit() else s.upper()


def numeric(number: str | None) -> int | None:
    s = (number or "").strip()
    return int(s) if s.isdigit() else None


def holders(db: Session, ws_id: int, account_id: int, number: str | None,
            exclude_id: int | None = None) -> list[RegisterTransaction]:
    key = check_key(number)
    if key is None:
        return []
    q = select(RegisterTransaction).where(RegisterTransaction.workspace_id == ws_id,
                                          RegisterTransaction.bank_account_id == account_id,
                                          RegisterTransaction.check_number.is_not(None),
                                          RegisterTransaction.status != "DELETED")   # 2.1.0 (#289)
    if exclude_id is not None:
        q = q.where(RegisterTransaction.id != exclude_id)
    return [t for t in db.scalars(q.order_by(RegisterTransaction.id)) if check_key(t.check_number) == key]


def assert_unused(db: Session, ws_id: int, account_id: int, number: str | None, exclude_id: int | None = None) -> None:
    used = holders(db, ws_id, account_id, number, exclude_id)
    if used:
        t = used[0]
        state = {"VOID": "a VOID record"}.get(t.status, "transaction")
        raise conflict("DUPLICATE_CHECK_NUMBER",
                       f"Check number {number} is already used in this account by {state} #{t.id} "
                       f"({t.transaction_date}). If that record has the wrong number, correct it first.",
                       transaction_id=t.id)


# ---------------------------------------------------------------------------------------------------------------------
# v1.3 CR-012: missing check review
#
# Per bank account, the purely numeric check numbers recorded on any record (active, VOID or zero-dollar VOID) are
# assumed to be used in sequence. Every number between the lowest and highest recorded number that no record carries is
# a possibly missing check, unless it was confirmed "not missing" with a note. Computed on the fly, so an item
# disappears as soon as the check is entered. Large gaps are reported as one range item.
RANGE_THRESHOLD = 25


def _subtract(ranges: list[tuple[int, int]], cut: tuple[int, int]) -> list[tuple[int, int]]:
    out = []
    for a, b in ranges:
        if cut[1] < a or cut[0] > b:
            out.append((a, b))
            continue
        if cut[0] > a:
            out.append((a, cut[0] - 1))
        if cut[1] < b:
            out.append((cut[1] + 1, b))
    return out


def _brief(t: RegisterTransaction) -> dict:
    return {"transaction_id": t.id, "check_number": t.check_number, "transaction_date": t.transaction_date.isoformat(),
            "status": t.status}


def review(db: Session, ws_id: int, account_id: int | None = None) -> dict:
    from ..models import BankAccount, CheckNumberAcknowledgement
    from .bank_accounts import masked
    from .common import covering_fiscal_years
    q = select(BankAccount).where(BankAccount.workspace_id == ws_id, BankAccount.register_enabled.is_(True))
    if account_id is not None:
        q = q.where(BankAccount.id == account_id)
    missing, duplicates = [], []
    for acct in db.scalars(q.order_by(BankAccount.account_name, BankAccount.id)):
        label = f"{acct.account_name} - {masked(acct)}"
        by_num: dict[int, list[RegisterTransaction]] = {}
        for t in db.scalars(select(RegisterTransaction).where(RegisterTransaction.workspace_id == ws_id,
                                                              RegisterTransaction.bank_account_id == acct.id,
                                                              RegisterTransaction.check_number.is_not(None),
                                                              RegisterTransaction.status != "DELETED")
                            .order_by(RegisterTransaction.id)):
            n = numeric(t.check_number)
            if n is not None:
                by_num.setdefault(n, []).append(t)
        for n, ts in sorted(by_num.items()):
            if len(ts) > 1:  # recorded before v1.3 enforced unique check numbers
                duplicates.append({"bank_account": {"id": acct.id, "label": label}, "check_number": n,
                                   "transactions": [_brief(t) for t in ts]})
        nums = sorted(by_num)
        acks = list(db.scalars(select(CheckNumberAcknowledgement)
                               .where(CheckNumberAcknowledgement.workspace_id == ws_id,
                                      CheckNumberAcknowledgement.bank_account_id == acct.id)))
        for lo, hi in zip(nums, nums[1:]):
            if hi - lo <= 1:
                continue
            gaps = [(lo + 1, hi - 1)]
            for a in acks:
                gaps = _subtract(gaps, (a.first_number, a.last_number))
            before, after = by_num[lo][0], by_num[hi][0]
            fys = {f.id for d in (before.transaction_date, after.transaction_date)
                   for f in covering_fiscal_years(db, ws_id, d)}
            for a, b in gaps:
                parts = [(a, b)] if b - a + 1 > RANGE_THRESHOLD else [(x, x) for x in range(a, b + 1)]
                for first, last in parts:
                    missing.append({"bank_account": {"id": acct.id, "label": label}, "first_number": first,
                                    "last_number": last, "count": last - first + 1, "before": _brief(before),
                                    "after": _brief(after), "fiscal_year_ids": sorted(fys)})
    return {"missing": missing, "duplicates": duplicates}


def acknowledge(db: Session, ctx, account_id: int, first: int, last: int, note: str):
    """Confirms that check numbers first..last (a single number when equal) are not missing."""
    from .. import audit
    from ..errors import validation
    from ..models import BankAccount, CheckNumberAcknowledgement
    from .common import get_scoped
    acct = get_scoped(db, BankAccount, account_id, ctx, "Bank Account")
    if first > last:
        raise validation("The first number must not be greater than the last.", "first_number")
    if last - first >= 1_000_000:
        raise validation("The range is too large.", "last_number")
    pending = [(m["first_number"], m["last_number"]) for m in review(db, ctx.workspace_id, acct.id)["missing"]]
    covered = sum(max(0, min(b, last) - max(a, first) + 1) for a, b in pending)
    if covered != last - first + 1:
        raise conflict("NOT_MISSING", "Only check numbers currently listed as possibly missing can be confirmed.")
    ack = CheckNumberAcknowledgement(workspace_id=ctx.workspace_id, bank_account_id=acct.id, first_number=first,
                                     last_number=last, note=note, created_by_user_id=ctx.user.id)
    db.add(ack)
    db.flush()
    audit.record(db, ctx, "CHECK_NUMBERS_CONFIRMED_NOT_MISSING", "bank_account", acct.id, None,
                 {"first_number": first, "last_number": last, "note": note})
    return ack


def closure_warning(db: Session, fy) -> dict | None:
    items = [m for m in review(db, fy.workspace_id)["missing"] if fy.id in m["fiscal_year_ids"]]
    if not items:
        return None
    n = sum(m["count"] for m in items)
    return {"code": "MISSING_CHECKS", "message": f"{n} check number(s) may be missing from the register "
                                                 f"(gaps in the check sequence).",
            "items": [{"bank_account_id": m["bank_account"]["id"], "first_number": m["first_number"],
                       "last_number": m["last_number"]} for m in items]}
