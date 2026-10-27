"""Request-scoped dependencies: DB session, authentication context, CSRF and permission checks."""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from dataclasses import dataclass, field

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .errors import AppError, forbidden
from .models import AuthSession, User, utcnow
from .permissions import permissions_for

SESSION_COOKIE = "fm_session"
PRE_CSRF_COOKIE = "fm_precsrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ANON_MUTATING_PATHS = {"/api/auth/login", "/api/system/initialize",
                       "/api/auth/forgot/start", "/api/auth/forgot/complete",  # 1.8.0 (#113)
                       "/api/system/demo/reset"}  # 2.2.0 (#243): from the sign-in page (exists only in the demo)
ANON_MUTATING_PREFIXES = ("/api/system/restore/",)  # v1.4.1 CR-024: restore from the initialization wizard


def _anon_path(path: str) -> bool:
    return path in ANON_MUTATING_PATHS or path.startswith(ANON_MUTATING_PREFIXES)


def get_db(request: Request):
    db: Session = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Ctx:
    user: User | None
    session: AuthSession | None
    workspace_id: int | None
    roles: set[str] = field(default_factory=set)
    perms: set[str] = field(default_factory=set)
    correlation_id: str | None = None
    ip: str | None = None
    # v1.4.1 CR-018: VERIFY / ENROLL while the MFA step is outstanding; 1.8.0 (#113): PASSWORD / QUESTIONS while a
    # setup step after the sign-in is outstanding
    mfa_pending: str | None = None

    def has(self, perm: str) -> bool:
        return perm in self.perms

    def require(self, perm: str) -> None:
        if perm not in self.perms:
            raise forbidden()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _load(request: Request, db: Session) -> Ctx:
    if hasattr(request.state, "ctx"):
        return request.state.ctx
    settings = request.app.state.settings
    ctx = Ctx(None, None, None, correlation_id=getattr(request.state, "correlation_id", None),
              ip=_client_ip(request))
    token = request.cookies.get(SESSION_COOKIE)
    if token and len(token) < 200:
        sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        now = utcnow()
        if sess and sess.revoked_at is None and sess.expires_at > now:
            idle = dt.timedelta(minutes=settings.session_idle_minutes)
            if sess.last_seen_at + idle < now:
                sess.revoked_at = now
                db.commit()
            else:
                user = db.get(User, sess.user_id)
                if user and user.active:
                    ip = (ctx.ip or "")[:64] or None
                    if (now - sess.last_seen_at).total_seconds() > 30 or (ip and sess.client_ip != ip):
                        sess.last_seen_at = now
                        sess.client_ip = ip or sess.client_ip   # 2.0.0 (#127): shown in the sessions list
                        db.commit()
                    ctx.user, ctx.session, ctx.workspace_id = user, sess, user.workspace_id
                    ctx.mfa_pending = sess.mfa_pending
                    if not sess.mfa_pending:  # an MFA-pending session carries no roles or permissions
                        ctx.roles = user.role_codes  # revalidated from the DB on every request (BR-087)
                        ctx.perms = permissions_for(ctx.roles)
    request.state.ctx = ctx
    return ctx


def enforce_csrf(request: Request, db: Session = Depends(get_db)) -> None:
    """Global dependency: every state-changing API request must carry a valid CSRF token (BR-088)."""
    if request.method in SAFE_METHODS or not request.url.path.startswith("/api/"):
        return
    header = request.headers.get(CSRF_HEADER, "")
    origin = request.headers.get("origin")
    if origin:
        host = request.headers.get("host", "")
        if origin.split("://", 1)[-1] != host:
            raise AppError(403, "CSRF_FAILED", "Cross-origin request rejected.")
    ctx = _load(request, db)
    if _anon_path(request.url.path):
        cookie = request.cookies.get(PRE_CSRF_COOKIE, "")
        if header and cookie and secrets.compare_digest(header, cookie):
            return
    if ctx.session is not None:
        if header and secrets.compare_digest(header, ctx.session.csrf_token):
            return
        raise AppError(403, "CSRF_FAILED", "Missing or invalid CSRF token.")
    if _anon_path(request.url.path):
        cookie = request.cookies.get(PRE_CSRF_COOKIE, "")
        if header and cookie and secrets.compare_digest(header, cookie):
            return
        raise AppError(403, "CSRF_FAILED", "Missing or invalid CSRF token.")
    # Unauthenticated mutation of a protected endpoint: authentication error.
    raise AppError(401, "UNAUTHENTICATED", "Authentication required.")


def enforce_maintenance(request: Request, db: Session = Depends(get_db)) -> None:
    """2.0.0 (#130): global dependency after the CSRF check - while maintenance mode is on, only Administrators may
    change anything (enforced on the backend for every state-changing request)."""
    if request.method in SAFE_METHODS or not request.url.path.startswith("/api/"):
        return
    from .services import maintenance
    maintenance.enforce(request, db, _load(request, db))


def get_ctx(request: Request, db: Session = Depends(get_db)) -> Ctx:
    return _load(request, db)


def auth_ctx(request: Request, db: Session = Depends(get_db)) -> Ctx:
    ctx = _load(request, db)
    if ctx.user is None:
        raise AppError(401, "UNAUTHENTICATED", "Authentication required.")
    if ctx.mfa_pending:  # v1.4.1 CR-018: password accepted, second step outstanding
        raise AppError(401, "MFA_REQUIRED", "Complete two-step verification to continue.")
    return ctx


def pre_mfa_ctx(request: Request, db: Session = Depends(get_db)) -> Ctx:
    """Signed-in user whose MFA step may still be outstanding (MFA verify/enroll, /auth/me, logout)."""
    ctx = _load(request, db)
    if ctx.user is None:
        raise AppError(401, "UNAUTHENTICATED", "Authentication required.")
    return ctx


def require(perm: str):
    def _dep(ctx: Ctx = Depends(auth_ctx)) -> Ctx:
        ctx.require(perm)
        return ctx

    return _dep
