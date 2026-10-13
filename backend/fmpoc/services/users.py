"""User administration (Administrator only) with security-domain separation (BR-002)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, conflict, validation
from ..models import Role, User, UserRole, utcnow
from ..permissions import ADMINISTRATOR, validate_role_set
from ..security.passwords import hash_password, policy_errors
from .auth import revoke_user_sessions
from .common import get_scoped


def snapshot(u: User) -> dict:
    return {"id": u.id, "username": u.username, "email": u.email, "display_name": u.display_name,
            "first_name": u.first_name, "last_name": u.last_name, "active": u.active,
            "security_domain": u.security_domain, "roles": sorted(u.role_codes)}


NAME_MAX = 60


def clean_person_name(value: str | None, field: str) -> str:
    """2.0.0 (#134): first and last name - required, trimmed, at most 60 characters, at least one letter (any
    language), no control characters. Stored and shown as plain text."""
    label = "First name" if field == "first_name" else "Last name"
    name = " ".join((value or "").split())
    if not name:
        raise validation(f"{label} is required.", field)
    if len(name) > NAME_MAX:
        raise validation(f"{label} can have at most {NAME_MAX} characters.", field)
    if not any(c.isalpha() for c in name) or any(ord(c) < 32 or 0x7f <= ord(c) < 0xa0 for c in name):
        raise validation(f"{label} must contain letters.", field)
    return name


def full_name(u: User) -> str | None:
    return f"{u.first_name} {u.last_name}" if u.first_name and u.last_name else None


def label(u: User) -> str:
    """"First Last - username" (#134), or the username alone while the names are missing."""
    n = full_name(u)
    return f"{n} - {u.username}" if n else u.username


def out(u: User) -> dict:
    return {**snapshot(u), "label": label(u), "name_needed": full_name(u) is None,
            "created_at": u.created_at.isoformat() + "Z",
            "password_changed_at": u.password_changed_at.isoformat() + "Z" if u.password_changed_at else None}


def _active_admin_count(db: Session, ws_id: int) -> int:
    return db.scalar(select(func.count(User.id)).join(UserRole, UserRole.user_id == User.id)
                     .join(Role, Role.id == UserRole.role_id)
                     .where(User.workspace_id == ws_id, User.active.is_(True), Role.code == ADMINISTRATOR)) or 0


def _set_roles(db: Session, u: User, codes: set[str]) -> None:
    roles = {r.code: r for r in db.scalars(select(Role))}
    for ur in db.scalars(select(UserRole).where(UserRole.user_id == u.id)):
        db.delete(ur)  # role assignment rows are security configuration, not business records; changes audited
    db.flush()
    for c in sorted(codes):
        db.add(UserRole(user_id=u.id, role_id=roles[c].id))
    db.flush()
    db.expire(u, ["roles"])


def _pw_check(pw: str, username: str) -> None:
    errs = policy_errors(pw, username)
    if errs:
        raise AppError(422, "PASSWORD_POLICY", " ".join(errs), errors=[{"field": "password", "message": e} for e in errs])


DISPLAY_NAME_MIN = 3


def clean_display_name(value: str | None) -> str:
    """1.7.1 (#47): every user has a display name - trimmed, at least 3 characters (the database enforces the same
    rule, migration 0017). It is what the top bar shows for the signed-in user (#46)."""
    name = (value or "").strip()
    if not name:
        raise validation("Display name is required.", "display_name")
    if len(name) < DISPLAY_NAME_MIN:
        raise validation(f"Display name must be at least {DISPLAY_NAME_MIN} characters.", "display_name")
    return name


def create(db: Session, ctx, data, mode: str = "server") -> User:
    display_name = clean_display_name(data.display_name)
    first, last = clean_person_name(data.first_name, "first_name"), clean_person_name(data.last_name, "last_name")
    err = validate_role_set(data.security_domain, set(data.roles), mode)
    if err:
        raise validation(err, "roles")
    if db.scalar(select(User.id).where(User.workspace_id == ctx.workspace_id,
                                       User.username_normalized == data.username.lower())):
        raise conflict("DUPLICATE_USERNAME", "That username is already in use.")
    _pw_check(data.password, data.username)
    u = User(workspace_id=ctx.workspace_id, username=data.username, username_normalized=data.username.lower(),
             email=data.email, display_name=display_name, first_name=first, last_name=last,
             password_hash=hash_password(data.password),
             active=True, security_domain=data.security_domain, theme="light", password_changed_at=utcnow(),
             created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id)
    db.add(u)
    db.flush()
    _set_roles(db, u, set(data.roles))
    audit.record(db, ctx, "USER_CREATED", "user", u.id, None, snapshot(u), category="SECURITY")
    return u


def update(db: Session, ctx, u: User, data, mode: str = "local") -> User:
    """mode (1.7.2, #55): in server mode an Administrator cannot change their own roles or security domain; another
    Administrator has to. A local install (one person, one computer) is not restricted."""
    before = snapshot(u)
    f = data.model_fields_set
    if "email" in f:
        if not data.email:
            raise validation("Email is required.", "email")
        u.email = data.email
    if "display_name" in f:   # sent empty = an attempt to remove it
        u.display_name = clean_display_name(data.display_name)
    # 2.0.0 (#134): names can be corrected but never removed; an account without names must get them with any edit
    if "first_name" in f or not u.first_name:
        u.first_name = clean_person_name(data.first_name if "first_name" in f else None, "first_name")
    if "last_name" in f or not u.last_name:
        u.last_name = clean_person_name(data.last_name if "last_name" in f else None, "last_name")
    domain = data.security_domain if "security_domain" in f and data.security_domain else u.security_domain
    roles_changed = False
    if "roles" in f or domain != u.security_domain:
        codes = set(data.roles) if data.roles is not None else u.role_codes
        # 1.9.0 (#54): unchanged roles are not re-validated, so a user with local-only combined roles can still be
        # edited (email, name, active) after the data moved to a server; changing the roles there needs one domain
        err = None if (codes == u.role_codes and domain == u.security_domain) else validate_role_set(domain, codes, mode)
        if err:
            raise validation(err, "roles")
        if codes != u.role_codes or domain != u.security_domain:
            if mode == "server" and u.id == ctx.user.id:
                raise AppError(403, "OWN_ROLES_LOCKED", "You cannot change your own roles. Another Administrator "
                                                        "can change them for you.")
            roles_changed = True
            u.security_domain = domain
            _set_roles(db, u, codes)
    if "active" in f and data.active is not None and data.active != u.active:
        if not data.active and u.id == ctx.user.id:
            # 1.7.2 (#55 follow-up): nobody disables their own account - it signs them out at once and, by mistake,
            # can leave the installation without the Administrator who meant to disable someone else. Any mode.
            raise AppError(403, "OWN_ACCOUNT_DISABLE", "You cannot disable your own account. Another Administrator "
                                                        "can disable it for you.")
        u.active = data.active
        if not u.active:
            revoke_user_sessions(db, u.id)  # disabled users lose authorization immediately
        else:   # 1.8.0 (#113): re-enabling also ends a lock and clears the count of failed attempts
            u.failed_attempts, u.locked_until = 0, None
    db.flush()
    if _active_admin_count(db, ctx.workspace_id) < 1:
        raise conflict("LAST_ADMINISTRATOR", "At least one active Administrator must remain.")
    u.updated_by_user_id = ctx.user.id
    action = "USER_UPDATED"
    if roles_changed:
        action = "USER_ROLES_CHANGED"
    if "active" in f and data.active is False and before["active"]:
        action = "USER_DISABLED"
    audit.record(db, ctx, action, "user", u.id, before, snapshot(u), category="SECURITY")
    return u


def reset_password(db: Session, ctx, u: User, new_password: str) -> None:
    _pw_check(new_password, u.username)
    u.password_hash = hash_password(new_password)
    u.password_changed_at = utcnow()
    u.updated_by_user_id = ctx.user.id
    n = revoke_user_sessions(db, u.id)
    from .mfa import revoke_trusted
    revoke_trusted(db, u.id)  # v1.4.1 CR-018: a password reset also ends "trusted browser" sign-ins
    audit.record(db, ctx, "USER_PASSWORD_RESET", "user", u.id, None, {"reset_by_administrator": True,
                                                                     "sessions_revoked": n}, category="SECURITY")


def get(db: Session, ctx, uid: int) -> User:
    return get_scoped(db, User, uid, ctx, "User")


# ------------------------------------------------------------------ 2.0.0 (#134) completing names after the upgrade
def names_needed(db: Session, ws_id: int) -> list[User]:
    return list(db.scalars(select(User).where(User.workspace_id == ws_id,
                                              (User.first_name.is_(None)) | (User.last_name.is_(None)))
                           .order_by(User.username_normalized)))


def complete_names(db: Session, ctx, rows: list) -> int:
    """Sets first and last name for accounts that lack them (all rows validated before any is saved)."""
    wanted = {u.id: u for u in names_needed(db, ctx.workspace_id)}
    clean = []
    for r in rows:
        u = wanted.get(r.id)
        if u is None:
            raise validation("That account does not need names (or does not exist).", "users")
        clean.append((u, clean_person_name(r.first_name, "first_name"), clean_person_name(r.last_name, "last_name")))
    for u, first, last in clean:
        before = snapshot(u)
        u.first_name, u.last_name, u.updated_by_user_id = first, last, ctx.user.id
        db.flush()
        audit.record(db, ctx, "USER_UPDATED", "user", u.id, before, snapshot(u), category="SECURITY")
    return len(clean)
