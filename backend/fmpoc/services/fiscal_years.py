"""Fiscal Years: naming, continuity/overlap safeguards, copy, approval, closure (BR-005..015, BR-FY-VIS-*)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, Warning_, conflict, require_confirmations, validation
from ..models import (Attachment, Budget, FiscalYear, FiscalYearReview, RegisterTransaction, TransactionAllocation,
                      utcnow)
from . import budgets as bsvc
from .common import active_allocation_totals, fy_brief, fy_label, get_scoped

ONE_DAY = dt.timedelta(days=1)


def snapshot(fy: FiscalYear) -> dict:
    return {"id": fy.id, "identifier": fy.identifier, "display_name": fy.display_name,
            "start_date": fy.start_date, "end_date": fy.end_date, "status": fy.status,
            "approved_at": fy.approved_at, "approved_by_user_id": fy.approved_by_user_id,
            "closed_at": fy.closed_at, "closed_by_user_id": fy.closed_by_user_id,
            "exception_confirmed": fy.exception_confirmed,
            "approval_no_attachment": bool(fy.approval_no_attachment),
            "approval_no_attachment_reason": fy.approval_no_attachment_reason}


def out(fy: FiscalYear) -> dict:
    return {**snapshot(fy), "label": fy_label(fy), "start_date": fy.start_date.isoformat(),
            "end_date": fy.end_date.isoformat(),
            "approved_at": fy.approved_at.isoformat() if fy.approved_at else None,
            "closed_at": fy.closed_at.isoformat() if fy.closed_at else None,
            "created_at": fy.created_at.isoformat() if fy.created_at else None}


def list_all(db: Session, ws_id: int) -> list[FiscalYear]:
    """All statuses - Draft is operational and never filtered out (AC-FY-VIS-010)."""
    return list(db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id).order_by(FiscalYear.start_date)))


def continuity_warnings(db: Session, ws_id: int, start: dt.date, end: dt.date, exclude_id: int | None) -> list[Warning_]:
    others = [f for f in list_all(db, ws_id) if f.id != exclude_id]
    warnings: list[Warning_] = []
    overlaps = [f for f in others if f.start_date <= end and start <= f.end_date]
    if overlaps:
        warnings.append(Warning_(
            "FY_OVERLAP",
            "WARNING: this Fiscal Year overlaps existing Fiscal Year(s). Overlap is only appropriate for an "
            "intentional fiscal-calendar change and makes transaction-date classification ambiguous.",
            overlapping=[{**fy_brief(f), "readiness": closure_check(db, f)} for f in overlaps],
        ))
    prior = max((f for f in others if f.end_date < start), key=lambda f: f.end_date, default=None)
    nxt = min((f for f in others if f.start_date > end), key=lambda f: f.start_date, default=None)
    gaps = []
    if prior and prior.end_date + ONE_DAY < start and not overlaps:
        gaps.append({"from": (prior.end_date + ONE_DAY).isoformat(), "to": (start - ONE_DAY).isoformat(),
                     "adjacent": fy_brief(prior), "expected_start_date": (prior.end_date + ONE_DAY).isoformat()})
    if nxt and end + ONE_DAY < nxt.start_date and not overlaps:
        gaps.append({"from": (end + ONE_DAY).isoformat(), "to": (nxt.start_date - ONE_DAY).isoformat(),
                     "adjacent": fy_brief(nxt), "expected_end_date": (nxt.start_date - ONE_DAY).isoformat()})
    if gaps:
        warnings.append(Warning_(
            "FY_GAP",
            "WARNING: this Fiscal Year leaves dates that are not covered by any Fiscal Year. "
            "Transactions on those dates will require Fiscal Year review.", gaps=gaps))
    return warnings


def _check_dates(start: dt.date, end: dt.date) -> None:
    if end < start:
        raise validation("End Date must be on or after Start Date.", "end_date")
    if (end - start).days > 800:
        raise validation("A Fiscal Year may not exceed 800 days.", "end_date")


def create(db: Session, ctx, data) -> FiscalYear:
    _check_dates(data.start_date, data.end_date)
    ident = data.identifier.upper()
    if db.scalar(select(FiscalYear.id).where(FiscalYear.workspace_id == ctx.workspace_id,
                                             func.upper(FiscalYear.identifier) == ident)):
        raise conflict("DUPLICATE_IDENTIFIER", f"FY{ident} already exists.")
    warnings = continuity_warnings(db, ctx.workspace_id, data.start_date, data.end_date, None)
    require_confirmations(warnings, data.confirmations)
    source = None
    if data.copy_from_fiscal_year_id is not None:
        source = get_scoped(db, FiscalYear, data.copy_from_fiscal_year_id, ctx, "Source Fiscal Year")
    fy = FiscalYear(workspace_id=ctx.workspace_id, identifier=ident, display_name=f"FY{ident}",
                    start_date=data.start_date, end_date=data.end_date, status="DRAFT",
                    exception_confirmed=",".join(sorted(w.code for w in warnings)) or None,
                    created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id)
    db.add(fy)
    db.flush()
    bsvc.create_budget_zero(db, ctx, fy)
    copied = []
    if source is not None:
        copied = copy_budgets(db, ctx, source, fy, data.copy_budget_ids)
    audit.record(db, ctx, "FISCAL_YEAR_CREATED", "fiscal_year", fy.id, None,
                 {**snapshot(fy), "confirmed_warnings": [w.code for w in warnings],
                  "copied_from_fiscal_year_id": source.id if source else None, "copied_budget_ids": copied})
    return fy


def copy_budgets(db: Session, ctx, source: FiscalYear, target: FiscalYear, parent_ids: list[int]) -> list[int]:
    """BR-027: carry forward code, name, type, hierarchy and prior amounts as Draft starting values."""
    wanted = set(parent_ids)
    parents = [b for b in db.scalars(select(Budget).where(Budget.fiscal_year_id == source.id,
                                                            Budget.parent_budget_id.is_(None),
                                                            Budget.system_managed.is_(False),
                                                            Budget.status != "DELETED"))]
    unknown = wanted - {p.id for p in parents}
    if unknown:
        raise validation("copy_budget_ids must reference parent budgets of the source Fiscal Year.", "copy_budget_ids")
    created = []
    link = source.start_date < target.start_date  # 1.8.0 (#89): a copy into a later year continues its source

    def _link(src: Budget) -> int | None:
        return src.id if link and bsvc._continued_by(db, src.id) is None else None
    for p in parents:
        if p.id not in wanted:
            continue
        np = Budget(workspace_id=target.workspace_id, fiscal_year_id=target.id, parent_code=p.parent_code,
                    name=p.name, budget_type=p.budget_type, amount_cents=p.amount_cents, status="DRAFT",
                    notes=p.notes, created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id,
                    continues_budget_id=_link(p), invoiced_income=bool(p.invoiced_income))   # 2.4.0 (#250)
        db.add(np)
        db.flush()
        explicit, _ = bsvc.children_of(db, p)
        for c in explicit:
            db.add(Budget(workspace_id=target.workspace_id, fiscal_year_id=target.id, parent_budget_id=np.id,
                          parent_code=np.parent_code, child_code=c.child_code, name=c.name,
                          budget_type=c.budget_type, amount_cents=c.amount_cents, status="DRAFT", notes=c.notes,
                          created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id,
                          continues_budget_id=_link(c), invoiced_income=bool(p.invoiced_income)))
        db.flush()
        bsvc.recalc_other(db, np)
        created.append(np.id)
    return created


def update(db: Session, ctx, fy: FiscalYear, data) -> FiscalYear:
    if fy.status != "DRAFT":
        raise conflict("INVALID_STATE", "Only Draft Fiscal Years can be edited; identity is preserved after approval.")
    before = snapshot(fy)
    start = data.start_date or fy.start_date
    end = data.end_date or fy.end_date
    _check_dates(start, end)
    if data.identifier and data.identifier.upper() != fy.identifier:
        ident = data.identifier.upper()
        if db.scalar(select(FiscalYear.id).where(FiscalYear.workspace_id == ctx.workspace_id,
                                                 func.upper(FiscalYear.identifier) == ident, FiscalYear.id != fy.id)):
            raise conflict("DUPLICATE_IDENTIFIER", f"FY{ident} already exists.")
        fy.identifier, fy.display_name = ident, f"FY{ident}"
    warnings = []
    if (start, end) != (fy.start_date, fy.end_date):
        warnings = continuity_warnings(db, ctx.workspace_id, start, end, fy.id)
        require_confirmations(warnings, data.confirmations)
        fy.exception_confirmed = ",".join(sorted(w.code for w in warnings)) or None
    fy.start_date, fy.end_date = start, end
    fy.updated_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "FISCAL_YEAR_UPDATED", "fiscal_year", fy.id, before,
                 {**snapshot(fy), "confirmed_warnings": [w.code for w in warnings]})
    return fy


def fy_document_counts(db: Session, fy: FiscalYear) -> dict[str, int]:
    rows = db.execute(select(Attachment.document_type, func.count(Attachment.id))
                      .where(Attachment.fiscal_year_id == fy.id, Attachment.active.is_(True))
                      .group_by(Attachment.document_type)).all()
    return {k or "UNSPECIFIED": n for k, n in rows}


def set_approval_no_attachment(db: Session, ctx, fy: FiscalYear, flag: bool, reason: str | None) -> FiscalYear:
    """v1.3 CR-007: record that the organization produces no budget-approval document."""
    if fy.status == "CLOSED":
        raise conflict("FISCAL_YEAR_CLOSED", "Closed Fiscal Year documentation cannot be changed.")
    if flag and fy_document_counts(db, fy).get("APPROVAL"):
        raise conflict("APPROVAL_DOCUMENT_PRESENT", "An approval document is already attached.")
    before = snapshot(fy)
    fy.approval_no_attachment = bool(flag)
    fy.approval_no_attachment_reason = reason if flag else None
    fy.approval_no_attachment_set_at = utcnow() if flag else None
    fy.approval_no_attachment_set_by_user_id = ctx.user.id if flag else None
    db.flush()
    audit.record(db, ctx, "FY_APPROVAL_NO_ATTACHMENT_SET" if flag else "FY_APPROVAL_NO_ATTACHMENT_CLEARED",
                 "fiscal_year", fy.id, before, snapshot(fy))
    return fy


def approve(db: Session, ctx, fy: FiscalYear, confirm: bool) -> FiscalYear:
    """BR-011: irreversible; validates structures and locks all active budgets.
    v1.3 CR-007: requires an Approval document, or the "no approval document" mark."""
    if fy.status != "DRAFT":
        raise conflict("INVALID_STATE", f"{fy.display_name} is already {fy.status.lower()}.")
    has_doc = bool(fy_document_counts(db, fy).get("APPROVAL"))
    if not has_doc and not fy.approval_no_attachment:
        raise conflict("APPROVAL_DOCUMENT_REQUIRED",
                       "Attach the budget approval document (e.g. signed approval or meeting minutes), or mark that "
                       "the organization produces no approval document, before approving the Fiscal Year.")
    if not confirm:
        warnings = [{"code": "IRREVERSIBLE", "message": "Approval cannot be reversed.", "details": {}}]
        if not has_doc:
            warnings.append({"code": "APPROVAL_NO_ATTACHMENT", "details": {},
                             "message": "No approval document is attached: the Fiscal Year is marked as having no "
                                        "approval document. This will be listed as a warning in the Fiscal Year review."})
        raise AppError(409, "CONFIRMATION_REQUIRED", "Approval is irreversible and requires confirmation.",
                       warnings=warnings)
    before = snapshot(fy)
    locked_ids = []
    for p in db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id, Budget.parent_budget_id.is_(None),
                                             Budget.status != "DELETED")):
        if not p.is_budget_zero:
            bsvc.recalc_other(db, p)  # validates hierarchy (children <= parent)
        for b in bsvc.family(db, p):
            if b.status in ("DRAFT", "APPROVED"):
                b.status = "APPROVED"
                b.locked = True
                locked_ids.append(b.id)
    fy.status = "APPROVED"
    fy.approved_at = utcnow()
    fy.approved_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "FISCAL_YEAR_APPROVED", "fiscal_year", fy.id, before,
                 {**snapshot(fy), "locked_budget_ids": locked_ids})
    return fy


def _fy_allocation_query(fy: FiscalYear):
    return (select(TransactionAllocation, RegisterTransaction)
            .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
            .join(Budget, Budget.id == TransactionAllocation.budget_id)
            .where(Budget.fiscal_year_id == fy.id, TransactionAllocation.removed_at.is_(None),
                   RegisterTransaction.status != "DELETED"))  # 1.7.3 (#53): deleted transactions are out


def closure_check(db: Session, fy: FiscalYear) -> dict:
    """BR-013 blockers and BR-014 warnings."""
    blockers, warnings = [], []
    if fy.status == "CLOSED":
        return {"can_close": False, "blockers": [{"code": "ALREADY_CLOSED", "message": "Fiscal Year is closed."}],
                "warnings": []}
    if fy.status != "APPROVED":
        blockers.append({"code": "NOT_APPROVED", "message": "Fiscal Year is not Approved."})
    budgets = list(db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id)))
    unlocked = [b for b in budgets if b.status in ("DRAFT", "APPROVED") and not b.locked]
    if unlocked:
        blockers.append({"code": "UNLOCKED_BUDGETS", "message": f"{len(unlocked)} budget(s) are unlocked.",
                         "budget_ids": [b.id for b in unlocked]})
    rows = db.execute(_fy_allocation_query(fy)).all()
    active = [(a, t) for a, t in rows if t.status == "ACTIVE"]
    uncleared = sorted({t.id for a, t in active if t.clear_date is None})
    if uncleared:
        blockers.append({"code": "UNCLEARED_TRANSACTIONS",
                         "message": f"{len(uncleared)} applicable transaction(s) are uncleared.",
                         "transaction_ids": uncleared})
    pending = db.scalars(
        select(FiscalYearReview).join(TransactionAllocation, TransactionAllocation.id == FiscalYearReview.transaction_allocation_id)
        .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
        .join(Budget, Budget.id == TransactionAllocation.budget_id)
        .where(FiscalYearReview.status == "PENDING", RegisterTransaction.status == "ACTIVE",
               TransactionAllocation.removed_at.is_(None),
               (Budget.fiscal_year_id == fy.id) | (FiscalYearReview.natural_fiscal_year_id == fy.id)
               | ((RegisterTransaction.transaction_date >= fy.start_date) & (RegisterTransaction.transaction_date <= fy.end_date)))
    ).all()
    if pending:
        blockers.append({"code": "UNRESOLVED_REVIEWS", "message": f"{len(pending)} Fiscal Year review item(s) are unresolved.",
                         "review_ids": [r.id for r in pending]})
    invalid = []
    by_budget = {b.id: b for b in budgets}
    txn_totals: dict[int, int] = {}
    for a, t in active:
        txn_totals[t.id] = t.total_cents
        b = by_budget.get(a.budget_id)
        expected = {"DEPOSIT": "INCOME", "WITHDRAWAL": "EXPENSE"}[t.transaction_type]
        if b is None or (not b.is_budget_zero and b.budget_type != expected):
            invalid.append(a.id)
        elif b.parent_budget_id is None and not b.is_budget_zero:
            invalid.append(a.id)  # allocation on a roll-up parent
        elif a.amount_cents <= 0:
            invalid.append(a.id)
    invalid += [tid for tid, tot in txn_totals.items() if tot <= 0]
    if invalid:
        blockers.append({"code": "INVALID_ALLOCATIONS", "message": f"{len(invalid)} invalid/incomplete allocation(s).",
                         "ids": invalid})
    docs = fy_document_counts(db, fy)  # v1.3 CR-007
    if not docs.get("AUDIT_SIGNOFF"):
        blockers.append({"code": "NO_AUDIT_SIGNOFF",
                         "message": "An Audit Signoff document is required to close the Fiscal Year."})
    approval_warning = None
    if not docs.get("APPROVAL"):
        if fy.approval_no_attachment:
            approval_warning = {"code": "APPROVAL_NO_ATTACHMENT", "message": "No budget approval document: the Fiscal "
                                "Year is marked as having no approval document" + (f" ({fy.approval_no_attachment_reason})."
                                                                                   if fy.approval_no_attachment_reason else ".")}
        else:
            blockers.append({"code": "APPROVAL_DOCUMENT_MISSING",
                             "message": "The budget approval document is missing. Attach it (or mark that the "
                                        "organization produces none) before closing."})
    # ---- warnings (non-blocking)
    totals = active_allocation_totals(db, [b.id for b in budgets])
    rejected_activity = [b.id for b in budgets if b.status == "REJECTED" and totals.get(b.id, 0)]
    if rejected_activity:
        warnings.append({"code": "REJECTED_BUDGET_ACTIVITY", "message": f"{len(rejected_activity)} rejected budget(s) have activity.",
                         "budget_ids": rejected_activity})
    # v1.4 CR-019: only expense budgets can be "over budget"; income above budget is not a warning.
    over = [b.id for b in budgets if not b.is_budget_zero and b.parent_budget_id is not None
            and b.budget_type != "INCOME" and totals.get(b.id, 0) > b.amount_cents]
    if over:
        warnings.append({"code": "OVER_BUDGET", "message": f"{len(over)} budget(s) are over budget.", "budget_ids": over})
    reviewed = db.scalar(
        select(func.count(FiscalYearReview.id)).join(TransactionAllocation, TransactionAllocation.id == FiscalYearReview.transaction_allocation_id)
        .join(Budget, Budget.id == TransactionAllocation.budget_id)
        .where(FiscalYearReview.status == "REVIEWED", Budget.fiscal_year_id == fy.id)) or 0
    if reviewed:
        warnings.append({"code": "REVIEWED_CROSS_FY", "message": f"{reviewed} reviewed cross-Fiscal-Year allocation(s)."})
    voided = {}
    for a, t in rows:
        if t.status == "VOID":
            voided.setdefault(t.id, []).append(by_budget.get(a.budget_id))
    # Budget 0 activity (e.g. zero-dollar accountability VOIDs) is valid and not a warning (BR-014)
    voided_ids = [tid for tid, bs in voided.items() if not all(b is not None and b.is_budget_zero for b in bs)]
    if voided_ids:
        warnings.append({"code": "VOIDED_TRANSACTIONS", "message": f"{len(voided_ids)} voided transaction(s).",
                         "transaction_ids": voided_ids})
    if approval_warning:
        warnings.append(approval_warning)
    from .checks import closure_warning as check_warning  # v1.3 CR-012: warning only
    cw = check_warning(db, fy)
    if cw:
        warnings.append(cw)
    # v1.2 documentation review: warnings only, never blockers (CR-005)
    from .documentation import closure_warnings as doc_warnings
    warnings.extend(doc_warnings(db, fy))
    return {"can_close": not blockers, "blockers": blockers, "warnings": warnings}


def close(db: Session, ctx, fy: FiscalYear, confirm_reviewed: bool) -> FiscalYear:
    check = closure_check(db, fy)
    if not check["can_close"]:
        raise AppError(409, "CLOSURE_BLOCKED", "The Fiscal Year cannot be closed.", blockers=check["blockers"],
                       warnings=check["warnings"])
    if not confirm_reviewed:
        raise AppError(409, "CONFIRMATION_REQUIRED",
                       "Confirm that the Fiscal Year has been reviewed and is approved for closure.",
                       warnings=[{"code": "CLOSE_REVIEWED", "message": "Closure is irreversible.", "details": {}},
                                 *check["warnings"]])
    before = snapshot(fy)
    fy.status = "CLOSED"
    fy.closed_at = utcnow()
    fy.closed_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "FISCAL_YEAR_CLOSED", "fiscal_year", fy.id, before,
                 {**snapshot(fy), "acknowledged_warnings": [w["code"] for w in check["warnings"]]})
    return fy
