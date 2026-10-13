"""2.0.0 (#127): Administrators see who is signed in and can end sessions. Ending a session revokes it server-side
(BR-087): the user's next request is refused and they must sign in again. Session tokens and cookies are never shown
or logged (BR-103); a session is referred to by its row number only."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import conflict, not_found
from ..models import AuthSession, User, utcnow


def _active_query(settings, ws_id: int):
    now = utcnow()
    idle = dt.timedelta(minutes=settings.session_idle_minutes)
    return (select(AuthSession, User).join(User, User.id == AuthSession.user_id)
            .where(User.workspace_id == ws_id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > now,
                   AuthSession.last_seen_at > now - idle)
            .order_by(AuthSession.last_seen_at.desc(), AuthSession.id.desc()))


def _iso(d: dt.datetime | None) -> str | None:
    return d.isoformat() + "Z" if d else None


def active(db: Session, settings, ctx) -> list[dict]:
    out = []
    for s, u in db.execute(_active_query(settings, ctx.workspace_id)).all():
        out.append({"ref": s.id, "user_id": u.id, "username": u.username, "display_name": u.display_name,
                    "signed_in_at": _iso(s.created_at), "last_activity_at": _iso(s.last_seen_at),
                    "client_ip": s.client_ip, "signing_in": s.mfa_pending is not None,
                    "current": ctx.session is not None and s.id == ctx.session.id})
    return out


def _revoke(rows) -> list[tuple[AuthSession, User]]:
    now = utcnow()
    for s, _u in rows:
        s.revoked_at = now
    return rows


def end_one(db: Session, settings, ctx, ref: int) -> None:
    row = next(((s, u) for s, u in db.execute(_active_query(settings, ctx.workspace_id)).all() if s.id == ref), None)
    if row is None:
        raise not_found("Session")
    if ctx.session is not None and row[0].id == ctx.session.id:
        raise conflict("OWN_SESSION", "This is your own session: use Sign out.")
    _revoke([row])
    db.flush()
    audit.record(db, ctx, "SESSION_ENDED_BY_ADMIN", "user", row[1].id, None,
                 {"username": row[1].username, "sessions": 1}, category="SECURITY")


def end_user(db: Session, settings, ctx, user_id: int) -> int:
    user = db.get(User, user_id)
    if user is None or user.workspace_id != ctx.workspace_id:
        raise not_found("User")
    rows = [(s, u) for s, u in db.execute(_active_query(settings, ctx.workspace_id)).all()
            if u.id == user_id and (ctx.session is None or s.id != ctx.session.id)]
    _revoke(rows)
    db.flush()
    audit.record(db, ctx, "SESSION_ENDED_BY_ADMIN", "user", user.id, None,
                 {"username": user.username, "sessions": len(rows)}, category="SECURITY")
    return len(rows)


def end_everyone(db: Session, settings, ctx) -> int:
    rows = [(s, u) for s, u in db.execute(_active_query(settings, ctx.workspace_id)).all()
            if ctx.session is None or s.id != ctx.session.id]
    _revoke(rows)
    db.flush()
    audit.record(db, ctx, "ALL_SESSIONS_ENDED_BY_ADMIN", "workspace", ctx.workspace_id, None,
                 {"sessions": len(rows), "users": len({u.id for _s, u in rows})}, category="SECURITY")
    return len(rows)
