from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..models import AuditEvent
from ..services import audit_readable as readable

router = APIRouter(prefix="/api/audit-events", tags=["audit"])

# Administrators may view the audit log but not financial content (BR-003): financial snapshots are withheld.
FINANCIAL_OBJECTS = {"fiscal_year", "budget", "entity", "bank_account", "register_transaction", "attachment",
                     "fiscal_year_review", "transaction_allocation"}
SORTS = {"timestamp": AuditEvent.timestamp, "action": AuditEvent.action, "object_type": AuditEvent.object_type,
         "id": AuditEvent.id}


def _out(e: AuditEvent, ctx: Ctx, db: Session | None = None) -> dict:
    withheld = e.object_type in FINANCIAL_OBJECTS and not ctx.has("audit.view_financial_snapshots")
    can_financial = ctx.has("audit.view_financial_snapshots")
    out = {"id": e.id, "timestamp": e.timestamp.isoformat() + "Z", "actor_user_id": e.actor_user_id,
            "actor_username": e.actor_username, "actor_name": e.actor_name, "action": e.action, "object_type": e.object_type,
            "object_id": e.object_id, "category": e.category,
            "before": None if withheld else e.before_snapshot, "after": None if withheld else e.after_snapshot,
            "snapshots_withheld": withheld, "correlation_id": e.correlation_id}
    if db is not None:   # 2.0.0 (#133): the readable view, withheld the same way as the snapshots
        out["readable"] = readable.readable(db, e, withheld, can_financial)
    return out


@router.get("")
def list_events(
    object_type: str | None = Query(None, max_length=40, pattern=r"^[a-z_]+$"),
    object_id: str | None = Query(None, max_length=40),
    action: str | None = Query(None, max_length=60, pattern=r"^[A-Z_]+$"),
    actor: str | None = Query(None, max_length=64),
    category: Literal["BUSINESS", "SECURITY"] | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    sort: Literal["timestamp", "action", "object_type", "id"] = "timestamp",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=10_000_000),
    db: Session = Depends(get_db),
    ctx: Ctx = Depends(require("audit.view")),
):
    q = select(AuditEvent).where((AuditEvent.workspace_id == ctx.workspace_id) | AuditEvent.workspace_id.is_(None))
    if object_type:
        q = q.where(AuditEvent.object_type == object_type)
    if object_id:
        q = q.where(AuditEvent.object_id == object_id)
    if action:
        q = q.where(AuditEvent.action == action)
    if actor:
        q = q.where(AuditEvent.actor_username == actor)
    if category:
        q = q.where(AuditEvent.category == category)
    if date_from:
        q = q.where(AuditEvent.timestamp >= dt.datetime.combine(date_from, dt.time.min))
    if date_to:
        q = q.where(AuditEvent.timestamp <= dt.datetime.combine(date_to, dt.time.max))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    col = SORTS[sort]  # explicit allowlist (BR-095)
    q = q.order_by(col.desc() if direction == "desc" else col.asc(), AuditEvent.id.desc()).limit(limit).offset(offset)
    return {"total": total, "items": [_out(e, ctx, db) for e in db.scalars(q)]}


@router.get("/meta")
def meta(db: Session = Depends(get_db), ctx: Ctx = Depends(require("audit.view"))):
    """2.0.0 (#133): readable names for the action and object-type filters (the codes present in this log)."""
    base = (AuditEvent.workspace_id == ctx.workspace_id) | AuditEvent.workspace_id.is_(None)
    actions = sorted(db.scalars(select(AuditEvent.action).where(base).distinct()))
    types = sorted(db.scalars(select(AuditEvent.object_type).where(base).distinct()))
    return {"actions": [{"code": a, "label": readable.action_label(a)} for a in actions],
            "object_types": [{"code": t, "label": readable.object_label(t)} for t in types]}
