"""Authentication, sessions, password changes and failed-login rate limiting."""
from __future__ import annotations

import datetime as dt
import secrets
import threading
import time
from collections import defaultdict, deque

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import audit
from ..deps import hash_token
from ..errors import AppError
from ..models import AuthSession, User, utcnow
from ..security.passwords import hash_password, policy_errors, verify_password
from . import mfa


class LoginRateLimiter:
    """Basic in-process failed-login limiter keyed by username and client IP."""

    def __init__(self, max_failures: int, window_seconds: int):
        self.max, self.window = max_failures, window_seconds
        self._fails: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float):
        q = self._fails[key]
        while q and q[0] < now - self.window:
            q.popleft()
        return q

    def blocked(self, *keys: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return any(len(self._prune(k, now)) >= self.max for k in keys)

    def fail(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for k in keys:
                self._prune(k, now).append(now)

    def reset(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._fails.pop(k, None)


def create_session(db: Session, settings, user: User, mfa_pending: str | None = None,
                   ip: str | None = None) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    if mfa_pending in ("PASSWORD", "QUESTIONS"):   # 1.8.0 (#113): setup steps take a little longer than a code
        life = dt.timedelta(minutes=mfa.ENROLL_PENDING_MINUTES)
    elif mfa_pending:
        life = dt.timedelta(minutes=mfa.PENDING_MINUTES)
    else:
        life = dt.timedelta(hours=settings.session_absolute_hours)
    sess = AuthSession(
        token_hash=hash_token(token), user_id=user.id, csrf_token=secrets.token_urlsafe(32),
        created_at=now, last_seen_at=now, expires_at=now + life, mfa_pending=mfa_pending,
        client_ip=(ip or None) and str(ip)[:64],
    )
    db.add(sess)
    db.flush()
    return token, sess


def revoke_user_sessions(db: Session, user_id: int, except_session_id: int | None = None) -> int:
    stmt = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if except_session_id is not None:
        stmt = stmt.where(AuthSession.id != except_session_id)
    return db.execute(stmt.values(revoked_at=utcnow())).rowcount or 0


def mfa_state(db: Session, settings, user: User, trusted_token: str | None) -> tuple[str | None, str]:
    """v1.4.1 CR-018: (pending state for the new session, how MFA was satisfied)."""
    if mfa.enabled(db, user):
        if mfa.check_trusted(db, user, trusted_token):
            return None, "trusted_browser"
        return "VERIFY", "pending"
    if mfa.required(settings):
        return "ENROLL", "pending"
    return None, "not_enabled"


def login(db: Session, settings, limiter: LoginRateLimiter, ctx, username: str, password: str, prior_token: str | None,
          trusted_token: str | None = None):
    """1.8.0 (#113): a known, active account has a persistent count of failed attempts in a row with escalating locks
    (services/recovery); during a lock the password is not checked. The in-memory limiter remains a brake per client
    address and handles unknown usernames the same way, so the answers do not tell whether an account exists."""
    from . import recovery
    uname = (username or "").strip().lower()
    ukey, ipkey = f"u:{uname}", f"ip:{ctx.ip}"
    user = db.scalar(select(User).where(User.username_normalized == uname))
    known = user is not None and user.active
    if limiter.blocked(ipkey) or (known and recovery.is_locked(user)) or (not known and limiter.blocked(ukey)):
        audit.record(db, ctx, "LOGIN_RATE_LIMITED", "user", user.id if known else None, None, {"username": uname[:64]},
                     category="SECURITY")
        db.commit()
        raise AppError(429, "RATE_LIMITED", recovery.LOCKED_MESSAGE)
    ok = verify_password(user.password_hash if user else None, password or "")
    if not ok or not known:
        limiter.fail(ipkey)
        if known:
            recovery.register_failure(db, settings, ctx, user, "sign_in")
        else:
            limiter.fail(ukey)
        audit.record(db, ctx, "LOGIN_FAILED", "user", user.id if user else None, None,
                     {"username": uname[:64], **({"failed_attempts": user.failed_attempts} if known else {})},
                     category="SECURITY")
        db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", "Invalid username or password.")
    limiter.reset(ukey, ipkey)
    recovery.clear_failures(user)
    # Session rotation: any session presented with the login request is revoked.
    if prior_token:
        db.execute(update(AuthSession).where(AuthSession.token_hash == hash_token(prior_token))
                   .values(revoked_at=utcnow()))
    pending, how = mfa_state(db, settings, user, trusted_token)
    if not pending:
        pending = recovery.gate_for(db, user)
    token, sess = create_session(db, settings, user, pending, ctx.ip)
    ctx.user, ctx.workspace_id = user, user.workspace_id
    audit.record(db, ctx, "LOGIN" if not pending else "LOGIN_PASSWORD_ACCEPTED", "user", user.id, None,
                 {"session_ref": sess.id, "mfa": how if not pending else pending.lower()}, category="SECURITY")
    db.commit()
    return user, token, sess


def logout(db: Session, ctx) -> None:
    if ctx.session is not None:
        ctx.session.revoked_at = utcnow()
        audit.record(db, ctx, "LOGOUT", "user", ctx.user.id, None, None, category="SECURITY")
        db.commit()


def check_current_password(db: Session, ctx, current: str, purpose: str) -> None:
    if not verify_password(ctx.user.password_hash, current or ""):
        audit.record(db, ctx, "PASSWORD_CHECK_FAILED", "user", ctx.user.id, None, {"purpose": purpose},
                     category="SECURITY")
        db.commit()
        raise AppError(400, "INCORRECT_PASSWORD", "The current password is incorrect.",
                       errors=[{"field": "current_password", "message": "The current password is incorrect."}])


def set_new_password(db: Session, ctx, new: str, confirm: str) -> None:
    """1.8.0 (#113): replaces the temporary password set with the host `reset-password` (sign-in step PASSWORD)."""
    user = ctx.user
    if new != confirm:
        raise AppError(422, "VALIDATION_ERROR", "New password and confirmation do not match.",
                       errors=[{"field": "new_password_confirmation", "message": "Passwords do not match."}])
    errs = policy_errors(new, user.username)
    if verify_password(user.password_hash, new or ""):
        errs.append("New password must differ from the temporary password.")
    if errs:
        raise AppError(422, "PASSWORD_POLICY", " ".join(errs),
                       errors=[{"field": "new_password", "message": e} for e in errs])
    user.password_hash = hash_password(new)
    user.password_changed_at = utcnow()
    user.must_change_password = False
    audit.record(db, ctx, "PASSWORD_CHANGED", "user", user.id, None, {"self_service": True, "temporary_replaced": True},
                 category="SECURITY")


def change_own_password(db: Session, ctx, current: str, new: str, confirm: str) -> None:
    """BR-SEC-SELF-001/002."""
    user = ctx.user
    if not verify_password(user.password_hash, current or ""):
        audit.record(db, ctx, "PASSWORD_CHANGE_FAILED", "user", user.id, None, {"reason": "incorrect_current_password"},
                     category="SECURITY")
        db.commit()
        raise AppError(400, "INCORRECT_PASSWORD", "The current password is incorrect.")
    if new != confirm:
        raise AppError(422, "VALIDATION_ERROR", "New password and confirmation do not match.",
                       errors=[{"field": "new_password_confirmation", "message": "Passwords do not match."}])
    errs = policy_errors(new, user.username)
    if new == current:
        errs.append("New password must differ from the current password.")
    if errs:
        raise AppError(422, "PASSWORD_POLICY", " ".join(errs),
                       errors=[{"field": "new_password", "message": e} for e in errs])
    user.password_hash = hash_password(new)
    user.password_changed_at = utcnow()
    revoked = revoke_user_sessions(db, user.id, except_session_id=ctx.session.id)
    trusted = mfa.revoke_trusted(db, user.id)  # v1.4.1 CR-018
    audit.record(db, ctx, "PASSWORD_CHANGED", "user", user.id, None,
                 {"self_service": True, "other_sessions_revoked": revoked, "trusted_browsers_revoked": trusted},
                 category="SECURITY")
    db.commit()


def complete_mfa(db: Session, settings, ctx, how: str) -> tuple[str, AuthSession]:
    """Replaces the pending session with the next one (new token - session rotation on privilege change): a full
    session, or (1.8.0, #113) the next setup step - a new password, then the security questions."""
    from . import recovery
    old = ctx.session
    old.revoked_at = utcnow()
    gate = recovery.gate_for(db, ctx.user)
    token, sess = create_session(db, settings, ctx.user, gate, ctx.ip)
    if gate is None:
        audit.record(db, ctx, "LOGIN", "user", ctx.user.id, None, {"session_ref": sess.id, "mfa": how},
                     category="SECURITY")
    ctx.session, ctx.mfa_pending = sess, gate
    return token, sess
