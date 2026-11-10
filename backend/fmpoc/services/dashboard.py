"""Role-aware POC dashboards (docs/05 §2)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (AuditEvent, BankAccount, Budget, FiscalYear, FiscalYearReview, RegisterTransaction,
                      TransactionAllocation, User)
from ..money import fmt, parse_amount
from . import bank_accounts as bank
from . import budgets as bsvc
from .common import active_allocation_totals, covering_fiscal_years, fy_brief
from .documentation import review as documentation_review
from .fiscal_years import list_all


def _current_fy(db: Session, ws_id: int) -> FiscalYear | None:
    today = dt.date.today()
    cov = covering_fiscal_years(db, ws_id, today)
    if cov:
        return next((f for f in cov if f.status != "CLOSED"), cov[0])
    fys = list_all(db, ws_id)
    return min(fys, key=lambda f: abs((f.start_date - today).days), default=None)


def _pending_reviews(db: Session, ws_id: int) -> int:
    return db.scalar(select(func.count(FiscalYearReview.id))
                     .join(TransactionAllocation, TransactionAllocation.id == FiscalYearReview.transaction_allocation_id)
                     .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
                     .where(FiscalYearReview.workspace_id == ws_id, FiscalYearReview.status == "PENDING",
                            RegisterTransaction.status == "ACTIVE", TransactionAllocation.removed_at.is_(None))) or 0


def financial(db: Session, ctx) -> dict:
    ws = ctx.workspace_id
    fy = _current_fy(db, ws)
    summary = None
    if fy is not None:
        t = bsvc.tree(db, fy)
        summary = {"income": t["income_summary"], "expense": t["expense_summary"]}
        from . import fy_progress
        summary["progress"] = fy_progress.progress(db, fy, summary)      # 2.4.0 (#553): the FY Progress box
    accounts = [bank.out(db, a) for a in db.scalars(select(BankAccount).where(
        BankAccount.workspace_id == ws, BankAccount.status == "ACTIVE").order_by(*bank.listing_order()))]
    uncleared = db.scalar(select(func.count(RegisterTransaction.id)).where(
        RegisterTransaction.workspace_id == ws, RegisterTransaction.status == "ACTIVE",
        RegisterTransaction.clear_date.is_(None))) or 0
    return {
        "kind": "financial",
        "current_fiscal_year": fy_brief(fy),
        "fiscal_years": [fy_brief(f) for f in list_all(db, ws)],
        "budget_summary": summary,
        "bank_accounts": [{"id": a["id"], "label": a["label"], "current_balance": a["current_balance"],
                           "is_primary": a["is_primary"], "register_enabled": a["register_enabled"]} for a in accounts],
        # v1.4 CR-021: total of the active accounts listed above.
        "bank_accounts_total": fmt(sum(parse_amount(a["current_balance"], allow_negative=True) for a in accounts)),
        # v1.5.0 CR-028: the same accounts in the two groups of the Bank Accounts page, each with a subtotal
        "bank_account_groups": [
            {"key": key, "label": label,
             "account_ids": [a["id"] for a in accounts if a["group"] == key],
             "total": fmt(sum(parse_amount(a["current_balance"], allow_negative=True)
                              for a in accounts if a["group"] == key))}
            for key, label in bank.GROUPS],
        "attention": {"pending_fiscal_year_reviews": _pending_reviews(db, ws), "uncleared_transactions": uncleared,
                      "documentation_warnings": len(documentation_review(db, fy)) if fy is not None else 0},
    }


def auditor(db: Session, ctx) -> dict:
    ws = ctx.workspace_id
    txn_count = db.scalar(select(func.count(RegisterTransaction.id)).where(RegisterTransaction.workspace_id == ws)) or 0
    void_count = db.scalar(select(func.count(RegisterTransaction.id)).where(
        RegisterTransaction.workspace_id == ws, RegisterTransaction.status == "VOID")) or 0
    cross = db.scalar(select(func.count(FiscalYearReview.id)).where(FiscalYearReview.workspace_id == ws)) or 0
    rejected = list(db.scalars(select(Budget).where(Budget.workspace_id == ws, Budget.status == "REJECTED")))
    totals = active_allocation_totals(db, [b.id for b in rejected])
    base = financial(db, ctx)
    return {
        **base, "kind": "auditor",
        "review_summary": {
            "transaction_count": txn_count, "voided_transaction_count": void_count,
            "cross_fiscal_year_allocation_count": cross,
            "pending_fiscal_year_reviews": _pending_reviews(db, ws),
            "rejected_budget_count": len(rejected),
            "rejected_budgets_with_activity": sum(1 for b in rejected if totals.get(b.id)),
            "rejected_budget_activity_total": fmt(sum(totals.values())),
        },
    }


def administrator(db: Session, ctx) -> dict:
    ws = ctx.workspace_id
    users = list(db.scalars(select(User).where(User.workspace_id == ws)))
    since = dt.datetime.utcnow() - dt.timedelta(hours=24)
    failed = db.scalar(select(func.count(AuditEvent.id)).where(
        AuditEvent.action.in_(["LOGIN_FAILED", "LOGIN_RATE_LIMITED", "MFA_FAILED"]), AuditEvent.timestamp >= since)) or 0
    by_domain: dict[str, int] = {}
    for u in users:
        if u.active:
            by_domain[u.security_domain] = by_domain.get(u.security_domain, 0) + 1
    return {"kind": "administrator", "user_count": len(users), "active_user_count": sum(u.active for u in users),
            "active_users_by_domain": by_domain, "failed_logins_24h": failed}
