"""2.0.0 (#130): maintenance mode set by an Administrator.

While it is on, everyone can sign in and read, but only Administrators can change anything: every other state-changing
API request is refused on the backend (503 MAINTENANCE) before it reaches the handler, so nothing is half done
(BR-077). Signing in and out, two-step verification and personal display preferences stay open. The mode is kept in the
database, so it survives a restart. A start time may be set: from the moment it is scheduled every user sees a banner
with the message and the start time. Restore (and reinitialize) keep using the stricter built-in restore maintenance,
which blocks everything until they finish or fail."""
from __future__ import annotations

import datetime as dt
import re

from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, validation
from ..models import Workspace, utcnow
from .bootstrap import current_workspace

MESSAGE_MAX = 500
MAX_AHEAD_DAYS = 60
# requests still allowed for everyone while maintenance mode is on
OPEN_PREFIXES = ("/api/auth/", "/api/me/preferences", "/api/system/status")
# build 13: POST requests that only look things up (they change no records, at most audit the look-up, like the GET
# reports do) - "you can still look things up" covers them too
READ_ONLY_POSTS = tuple(re.compile(p) for p in (
    r"^/api/reports/financial-flow(/review)?$",   # Financial Flow Report: review and PDF
    r"^/api/audit-events/export$",                # audit log CSV/PDF export (#188)
    r"^/api/bank-accounts/\d+/reveal$",           # show the full account number (audited)
    r"^/api/fundraisers/preview$",                # which transactions a fundraiser filter matches
))


def _iso(d: dt.datetime | None) -> str | None:
    return d.replace(microsecond=0).isoformat() + "Z" if d else None


def state(ws: Workspace | None, now: dt.datetime | None = None) -> dict:
    if ws is None or not ws.maintenance_message:
        return {"on": False, "active": False}
    now = now or utcnow()
    active = ws.maintenance_starts_at is None or ws.maintenance_starts_at <= now
    return {"on": True, "active": active, "scheduled": not active, "message": ws.maintenance_message,
            "starts_at": _iso(ws.maintenance_starts_at), "set_by": ws.maintenance_set_by, "set_at": _iso(ws.maintenance_set_at)}


def current(db: Session) -> dict:
    return state(current_workspace(db))


def _clean(message: str) -> str:
    m = (message or "").replace("\r\n", "\n").strip()
    if not m or len(m) > MESSAGE_MAX:
        raise validation(f"A message for the users is required (at most {MESSAGE_MAX} characters).", "message")
    if any(ord(c) < 32 and c != "\n" for c in m):
        raise validation("The message can't contain control characters.", "message")
    return m


def turn_on(db: Session, ctx, message: str, starts_at: dt.datetime | None) -> dict:
    m = _clean(message)
    now = utcnow()
    if starts_at is not None:
        if starts_at.tzinfo is not None:
            starts_at = starts_at.astimezone(dt.timezone.utc).replace(tzinfo=None)
        if starts_at > now + dt.timedelta(days=MAX_AHEAD_DAYS):
            raise validation(f"The start can be at most {MAX_AHEAD_DAYS} days ahead.", "starts_at")
        if starts_at <= now:
            starts_at = None
    ws = db.get(Workspace, ctx.workspace_id)
    before = state(ws)
    ws.maintenance_message, ws.maintenance_starts_at = m, starts_at
    ws.maintenance_set_by, ws.maintenance_set_at = ctx.user.username, now
    db.flush()
    audit.record(db, ctx, "MAINTENANCE_MODE_ON" if not before["on"] else "MAINTENANCE_MODE_CHANGED", "workspace", ws.id,
                 {k: before.get(k) for k in ("message", "starts_at")} if before["on"] else None,
                 {"message": m, "starts_at": _iso(starts_at)}, category="SECURITY")
    return state(ws)


def turn_off(db: Session, ctx) -> dict:
    ws = db.get(Workspace, ctx.workspace_id)
    before = state(ws)
    if before["on"]:
        ws.maintenance_message = ws.maintenance_starts_at = None
        ws.maintenance_set_by, ws.maintenance_set_at = ctx.user.username, utcnow()
        db.flush()
        audit.record(db, ctx, "MAINTENANCE_MODE_OFF", "workspace", ws.id,
                     {"message": before["message"], "starts_at": before.get("starts_at")}, None, category="SECURITY")
    return state(ws)


def enforce(request, db: Session, ctx) -> None:
    """Called for every state-changing API request after the CSRF check."""
    path = request.url.path
    if any(path.startswith(p) for p in OPEN_PREFIXES) or ctx.user is None or ctx.has("system.manage"):
        return
    if request.method == "POST" and any(r.match(path) for r in READ_ONLY_POSTS):
        return
    st = state(db.get(Workspace, ctx.workspace_id) if ctx.workspace_id else None)
    if st["active"]:
        raise AppError(503, "MAINTENANCE", f"Maintenance: {st['message']} (changes are paused; you can still look "
                                           "things up).")
