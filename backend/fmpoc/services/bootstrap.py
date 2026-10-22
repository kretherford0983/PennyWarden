"""First-run initialization (BR-INIT-001..004, AC-SEC-001, AC-INIT-*)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError
from ..models import Entity, Role, User, UserRole, Workspace, utcnow
from ..permissions import ADMINISTRATOR, COMBINED, LOCAL_FIRST_USER_ROLES, ROLE_DEFS
from ..security import crypto
from ..security.passwords import hash_password

MULTIPLE_ENTITY_NUMBER = "ENT-000000"


def current_workspace(db: Session) -> Workspace | None:
    return db.scalar(select(Workspace).where(Workspace.bootstrap_completed_at.is_not(None)).order_by(Workspace.id))


def is_initialized(db: Session) -> bool:
    """Bootstrap state - not mere existence of a database file (docs/06 v1.1, AC-INIT-008)."""
    ws = current_workspace(db)
    if ws is None:
        return False
    admin = db.scalar(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.workspace_id == ws.id, Role.code == ADMINISTRATOR)
        .limit(1)
    )
    return admin is not None


def seed_roles(db: Session) -> dict[str, Role]:
    existing = {r.code: r for r in db.scalars(select(Role))}
    for code, name, domain in ROLE_DEFS:
        if code not in existing:
            r = Role(code=code, name=name, security_domain=domain)
            db.add(r)
            existing[code] = r
    db.flush()
    return existing


def initialize(db: Session, settings, ctx, *, workspace_name: str, username: str, email: str, password: str,
               first_name: str | None = None, last_name: str | None = None) -> User:
    if is_initialized(db):
        raise AppError(409, "ALREADY_INITIALIZED", "The application has already been initialized.")
    km = crypto.load_or_create_key(settings.secrets_dir)
    ws = db.scalar(select(Workspace).where(Workspace.bootstrap_completed_at.is_(None)).order_by(Workspace.id))
    if ws is None:
        ws = Workspace(name=workspace_name)
        db.add(ws)
    ws.name = workspace_name
    ws.key_check = km.check_value
    ws.next_entity_number = 1
    db.flush()
    roles = seed_roles(db)
    # 1.9.0 (#54): on a local install the first user holds every role (one person runs the organization's books);
    # a server keeps the Administrator alone in the Administrator domain
    first_roles = LOCAL_FIRST_USER_ROLES if settings.mode == "local" else [ADMINISTRATOR]
    admin = User(
        workspace_id=ws.id,
        username=username,
        username_normalized=username.lower(),
        email=email,
        display_name=username,   # 1.7.1 (#47): required; the Administrator changes it under Users
        first_name=first_name, last_name=last_name,   # 2.0.0 (#134)
        password_hash=hash_password(password),
        active=True,
        security_domain=COMBINED if len(first_roles) > 1 else "ADMINISTRATOR",
        theme="light",
        password_changed_at=utcnow(),
    )
    db.add(admin)
    db.flush()
    for code in first_roles:
        db.add(UserRole(user_id=admin.id, role_id=roles[code].id))
    if not db.scalar(select(Entity).where(Entity.workspace_id == ws.id, Entity.is_system.is_(True))):
        db.add(Entity(
            workspace_id=ws.id, entity_number=MULTIPLE_ENTITY_NUMBER, entity_type="SYSTEM",
            organization_name="Multiple", is_system=True, active=True, name_key="multiple",
        ))
    from . import organization            # 2.1.0 (#314): the organization itself, as an entity
    organization.ensure(db, ws)
    ws.bootstrap_completed_at = utcnow()
    db.flush()
    db.refresh(admin)
    ctx.workspace_id, ctx.user = ws.id, admin
    audit.record(db, ctx, "SYSTEM_INITIALIZED", "workspace", ws.id, None,
                 {"workspace_name": ws.name, "admin_username": admin.username, "admin_email": admin.email,
                  "admin_roles": first_roles, "mode": settings.mode},
                 category="SECURITY")
    return admin
