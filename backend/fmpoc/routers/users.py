from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from ..deps import Ctx, get_db, require
from ..models import User, UserMfa
from ..schemas import MfaResetIn, MfaResetUserIn, NamesIn, PasswordResetIn, UserCreateIn, UserUpdateIn
from ..services import mfa as mfa_svc
from ..services import recovery
from ..services import users as svc

router = APIRouter(prefix="/api/users", tags=["users"])


def _mfa_on(db: Session) -> set[int]:
    return set(db.scalars(select(UserMfa.user_id).where(UserMfa.enabled_at.is_not(None))))


def _out(u: User, on: set[int]) -> dict:
    db = object_session(u)
    locked = recovery.is_locked(u)
    return {**svc.out(u), "mfa_enabled": u.id in on,  # v1.4.1 CR-018
            # 1.8.0 (#113)
            "security_questions_set": recovery.has_questions(db, u), "failed_attempts": u.failed_attempts or 0,
            "locked_until": u.locked_until.isoformat() + "Z" if locked else None}


@router.get("")
def list_users(db: Session = Depends(get_db), ctx: Ctx = Depends(require("users.view"))):
    on = _mfa_on(db)
    return [_out(u, on) for u in db.scalars(select(User).where(User.workspace_id == ctx.workspace_id).order_by(User.username))]


@router.get("/names-needed")
def names_needed(db: Session = Depends(get_db), ctx: Ctx = Depends(require("users.manage"))):
    """2.0.0 (#134): accounts from before 2.0.0 without first and last name (inactive ones too)."""
    return [{"id": u.id, "username": u.username, "display_name": u.display_name, "email": u.email,
             "active": u.active, "first_name": u.first_name, "last_name": u.last_name}
            for u in svc.names_needed(db, ctx.workspace_id)]


@router.put("/names")
def complete_names(body: NamesIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("users.manage"))):
    n = svc.complete_names(db, ctx, body.users)
    db.commit()
    return {"updated": n, "remaining": len(svc.names_needed(db, ctx.workspace_id))}


@router.get("/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("users.view"))):
    return _out(svc.get(db, ctx, user_id), _mfa_on(db))


@router.post("/{user_id}/reset-mfa")
def reset_mfa(user_id: int, body: MfaResetUserIn, db: Session = Depends(get_db),
              ctx: Ctx = Depends(require("users.manage"))):
    """v1.4.1 CR-018: the user sets two-step verification up again at the next sign-in (audited, reason required).
    2.2.0 (#327): `compromised` - the next setup accepts only a newly generated key."""
    u = svc.get(db, ctx, user_id)
    mfa_svc.reset(db, ctx, u, body.reason, compromised=body.compromised)
    db.commit()
    return _out(u, _mfa_on(db))


@router.post("/{user_id}/reset-security-questions")
def reset_questions(user_id: int, body: MfaResetIn, db: Session = Depends(get_db),
                    ctx: Ctx = Depends(require("users.manage"))):
    """1.8.0 (#113): the user chooses new security questions at the next sign-in (audited, reason required)."""
    u = svc.get(db, ctx, user_id)
    recovery.admin_reset_questions(db, ctx, u, body.reason)
    db.commit()
    return _out(u, _mfa_on(db))


@router.post("", status_code=201)
def create_user(body: UserCreateIn, request: Request, db: Session = Depends(get_db),
                ctx: Ctx = Depends(require("users.manage"))):
    u = svc.create(db, ctx, body, mode=request.app.state.settings.mode)  # 1.9.0 (#54): combined roles when local
    db.commit()
    return svc.out(u)


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserUpdateIn, request: Request, db: Session = Depends(get_db),
                ctx: Ctx = Depends(require("users.manage"))):
    u = svc.update(db, ctx, svc.get(db, ctx, user_id), body, mode=request.app.state.settings.mode)
    db.commit()
    return svc.out(u)


@router.post("/{user_id}/reset-password")
def reset_password(user_id: int, body: PasswordResetIn, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("users.manage"))):
    svc.reset_password(db, ctx, svc.get(db, ctx, user_id), body.new_password)
    db.commit()
    return {"ok": True}
