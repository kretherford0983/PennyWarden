from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..audit import actor_name
from ..deps import Ctx, get_db, require
from ..errors import AppError
from ..models import AuditEvent, Workspace
from ..services import audit_export as export
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


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_type: str | None = Field(None, max_length=40, pattern=r"^[a-z_]+$")
    object_id: str | None = Field(None, max_length=40)
    action: str | None = Field(None, max_length=60, pattern=r"^[A-Z_]+$")
    actor: str | None = Field(None, max_length=64)
    category: Literal["BUSINESS", "SECURITY"] | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    sort: Literal["timestamp", "action", "object_type", "id"] = "timestamp"
    direction: Literal["asc", "desc"] = "desc"


def _query(f: Filters, ctx: Ctx):
    """The filtered, ordered audit list - the screen and the export (#188) use the same query."""
    q = select(AuditEvent).where((AuditEvent.workspace_id == ctx.workspace_id) | AuditEvent.workspace_id.is_(None))
    if f.object_type:
        q = q.where(AuditEvent.object_type == f.object_type)
    if f.object_id:
        q = q.where(AuditEvent.object_id == f.object_id)
    if f.action:
        q = q.where(AuditEvent.action == f.action)
    if f.actor:
        q = q.where(AuditEvent.actor_username == f.actor)
    if f.category:
        q = q.where(AuditEvent.category == f.category)
    if f.date_from:
        q = q.where(AuditEvent.timestamp >= dt.datetime.combine(f.date_from, dt.time.min))
    if f.date_to:
        q = q.where(AuditEvent.timestamp <= dt.datetime.combine(f.date_to, dt.time.max))
    return q


def _ordered(q, f: Filters):
    col = SORTS[f.sort]  # explicit allowlist (BR-095)
    return q.order_by(col.desc() if f.direction == "desc" else col.asc(), AuditEvent.id.desc())


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
    f = Filters(object_type=object_type, object_id=object_id, action=action, actor=actor, category=category,
                date_from=date_from, date_to=date_to, sort=sort, direction=direction)
    q = _query(f, ctx)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    q = _ordered(q, f).limit(limit).offset(offset)
    return {"total": total, "items": [_out(e, ctx, db) for e in db.scalars(q)]}


class ExportIn(Filters):
    format: Literal["csv", "pdf"]
    time_zone: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_+\-/]+$")


@router.post("/export")
def export_events(body: ExportIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("audit.view"))):
    """2.0.0 build 12 (#188): the filtered audit list, readable, as CSV or a printable PDF. Same entries, order and
    withholding as the screen; audited (AUDIT_LOG_EXPORTED). POST: it writes an audit record (CSRF-protected)."""
    q = _query(body, ctx)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    if total > export.MAX_EXPORT:
        raise AppError(422, "EXPORT_TOO_LARGE", f"{total:,} entries match the filters; an export holds at most "
                       f"{export.MAX_EXPORT:,}. Narrow the filters (for example the dates) and export in parts.")
    entries = []
    for e in db.scalars(_ordered(q, body)):
        o = _out(e, ctx, db)
        o["_ts"] = e.timestamp
        entries.append(o)
    tz, tz_name = export.zone(body.time_zone)
    flt = body.model_dump(exclude={"format", "time_zone", "sort"}, exclude_none=True, mode="json")
    words = export.filter_lines(flt, {"object": readable.object_label, "action": readable.action_label})
    # recorded before the file is built, in the same transaction (the export itself is not in the file)
    audit.record(db, ctx, "AUDIT_LOG_EXPORTED", "audit_log", None, None,
                 {"format": body.format.upper(), "entries": total, "filters": flt, "time_zone": tz_name},
                 category="SECURITY")
    stamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    if body.format == "csv":
        data, media, name = export.to_csv(entries, tz, tz_name).encode("utf-8"), "text/csv; charset=utf-8", \
            f"audit-log-{stamp}.csv"
    else:
        ws = db.get(Workspace, ctx.workspace_id)
        who = f"{actor_name(ctx.user)} - {ctx.user.username}" if actor_name(ctx.user) else ctx.user.username
        data = export.to_pdf(entries, tz, tz_name, org=ws.name if ws else "PennyWarden", exported_by=who,
                             filters=words, total=total)
        media, name = "application/pdf", f"audit-log-{stamp}.pdf"
    db.commit()
    return Response(data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff", "X-Entry-Count": str(total)})


@router.get("/meta")
def meta(db: Session = Depends(get_db), ctx: Ctx = Depends(require("audit.view"))):
    """2.0.0 (#133): readable names for the action and object-type filters (the codes present in this log)."""
    base = (AuditEvent.workspace_id == ctx.workspace_id) | AuditEvent.workspace_id.is_(None)
    actions = sorted(db.scalars(select(AuditEvent.action).where(base).distinct()))
    types = sorted(db.scalars(select(AuditEvent.object_type).where(base).distinct()))
    return {"actions": [{"code": a, "label": readable.action_label(a)} for a in actions],
            "object_types": [{"code": t, "label": readable.object_label(t)} for t in types]}
