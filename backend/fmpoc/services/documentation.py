"""Fiscal Year documentation review (change request CR-005, rule revised in v1.2.1).

Lists ACTIVE transactions that affect a Fiscal Year and either lack supporting documentation
("MISSING_ATTACHMENTS") or are documented by a "no attachment will be provided" marker ("NO_ATTACHMENT_MARKED").
These are Fiscal Year review *warnings*; they never block approval or closure.

Rule (as specified by the product owner):
    IF the parent (transaction) has no attachment AND the parent has no no-attachment indicator
    THEN every child (allocation) must have either an attachment or its own no-attachment indicator
    ELSE (parent has an attachment OR parent has the indicator)
         children need neither and are not subject to documentation review.
A normal (unsplit) transaction is the same rule with a single child.

v1.4 CR-017: a no-attachment indicator WITH a (non-blank) reason counts as documented and is not listed; only an
indicator without a reason is still reported ("NO_ATTACHMENT_MARKED"). This applies to the review list, the closure
warnings and the dashboard count alike.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Attachment, BankAccount, Budget, FiscalYear, RegisterTransaction, TransactionAllocation
from ..money import fmt
from .common import entity_brief


@dataclass(frozen=True)
class Child:
    attachments: int
    no_attachment: bool
    has_reason: bool = False


def has_reason(reason: str | None) -> bool:
    return bool((reason or "").strip())


def classify(parent_attachments: int, parent_no_attachment: bool, children: list[Child],
             parent_has_reason: bool = False) -> str | None:
    """Returns None (documented), "MISSING_ATTACHMENTS" or "NO_ATTACHMENT_MARKED" (indicator without a reason)."""
    if parent_attachments > 0:
        return None
    if parent_no_attachment:
        return None if parent_has_reason else "NO_ATTACHMENT_MARKED"
    if any(c.attachments == 0 and not c.no_attachment for c in children):
        return "MISSING_ATTACHMENTS"
    if any(c.attachments == 0 and c.no_attachment and not c.has_reason for c in children):
        return "NO_ATTACHMENT_MARKED"
    return None


def _counts(db: Session, txn_ids: list[int], alloc_ids: list[int]) -> tuple[dict[int, int], dict[int, int]]:
    tc: dict[int, int] = {}
    ac: dict[int, int] = {}
    if txn_ids:
        for tid, n in db.execute(select(Attachment.transaction_id, func.count(Attachment.id))
                                 .where(Attachment.transaction_id.in_(txn_ids), Attachment.active.is_(True))
                                 .group_by(Attachment.transaction_id)):
            tc[tid] = n
    if alloc_ids:
        for aid, n in db.execute(select(Attachment.allocation_id, func.count(Attachment.id))
                                 .where(Attachment.allocation_id.in_(alloc_ids), Attachment.active.is_(True))
                                 .group_by(Attachment.allocation_id)):
            ac[aid] = n
    return tc, ac


def categories(db: Session, txns: list[RegisterTransaction]) -> dict[int, str | None]:
    """2.1.0 (#258): the review's classification for the given transactions - the register's Attachments filter uses
    this, so its "Missing" list is exactly what the review warns about. Only ACTIVE transactions are reviewed; others
    map to None."""
    active = [t for t in txns if t.status == "ACTIVE"]
    tc, ac = _counts(db, [t.id for t in active], [a.id for t in active for a in t.live_allocations])
    out: dict[int, str | None] = {t.id: None for t in txns}
    for t in active:
        children = [Child(ac.get(a.id, 0), bool(a.no_attachment), has_reason(a.no_attachment_reason))
                    for a in t.live_allocations]
        out[t.id] = classify(tc.get(t.id, 0), bool(t.no_attachment), children, has_reason(t.no_attachment_reason))
    return out


def is_marked(t: RegisterTransaction) -> bool:
    """2.1.0 (#258): carries a "no attachment will be provided" mark, on the transaction or on any live allocation."""
    return bool(t.no_attachment) or any(a.no_attachment for a in t.live_allocations)


def applicable_transactions(db: Session, fy: FiscalYear) -> list[RegisterTransaction]:
    """ACTIVE transactions with at least one live allocation to a budget of this Fiscal Year."""
    ids = db.scalars(select(RegisterTransaction.id).distinct()
                     .join(TransactionAllocation, TransactionAllocation.transaction_id == RegisterTransaction.id)
                     .join(Budget, Budget.id == TransactionAllocation.budget_id)
                     .where(Budget.fiscal_year_id == fy.id, RegisterTransaction.status == "ACTIVE",
                            TransactionAllocation.removed_at.is_(None))).all()
    if not ids:
        return []
    return list(db.scalars(select(RegisterTransaction).where(RegisterTransaction.id.in_(ids))
                           .order_by(RegisterTransaction.transaction_date, RegisterTransaction.id)))


def review(db: Session, fy: FiscalYear) -> list[dict]:
    txns = applicable_transactions(db, fy)
    alloc_ids = [a.id for t in txns for a in t.live_allocations]
    tc, ac = _counts(db, [t.id for t in txns], alloc_ids)
    accounts: dict[int, BankAccount] = {}
    items = []
    for t in txns:
        allocs = t.live_allocations
        parent = tc.get(t.id, 0)
        children = [Child(ac.get(a.id, 0), bool(a.no_attachment), has_reason(a.no_attachment_reason)) for a in allocs]
        category = classify(parent, bool(t.no_attachment), children, has_reason(t.no_attachment_reason))
        if category is None:
            continue
        acct = accounts.get(t.bank_account_id) or db.get(BankAccount, t.bank_account_id)
        accounts[t.bank_account_id] = acct
        from .bank_accounts import masked
        items.append({
            "transaction_id": t.id, "category": category, "transaction_date": t.transaction_date.isoformat(),
            "transaction_type": t.transaction_type, "total": fmt(t.total_cents), "is_split": len(allocs) > 1,
            "is_transfer": t.transfer_group is not None,
            "bank_account": {"id": acct.id, "label": f"{acct.account_name} - {masked(acct)}"},
            "entity": entity_brief(t.parent_entity), "parent_attachment_count": parent,
            "parent_no_attachment": bool(t.no_attachment),
            "allocations_without_documentation": ([] if parent or t.no_attachment else
                                                  [a.id for a, c in zip(allocs, children)
                                                   if c.attachments == 0 and not c.no_attachment]),
            "allocations_marked_no_attachment": ([] if parent or t.no_attachment else
                                                 [a.id for a, c in zip(allocs, children)
                                                  if c.attachments == 0 and c.no_attachment and not c.has_reason]),
            "allocation_count": len(allocs),
            "no_attachment_reason": t.no_attachment_reason or "; ".join(
                a.no_attachment_reason for a in allocs if a.no_attachment and a.no_attachment_reason) or None,
            "description": "; ".join(a.description for a in allocs if a.description)[:300] or None,
        })
    return items


def closure_warnings(db: Session, fy: FiscalYear) -> list[dict]:
    items = review(db, fy)
    out = []
    missing = [i["transaction_id"] for i in items if i["category"] == "MISSING_ATTACHMENTS"]
    marked = [i["transaction_id"] for i in items if i["category"] == "NO_ATTACHMENT_MARKED"]
    if missing:
        out.append({"code": "MISSING_ATTACHMENTS", "message": f"{len(missing)} transaction(s) have no supporting attachments.",
                    "transaction_ids": missing})
    if marked:
        out.append({"code": "NO_ATTACHMENT_MARKED",
                    "message": f"{len(marked)} transaction(s) are marked 'no attachment will be provided' without a reason.",
                    "transaction_ids": marked})
    return out
