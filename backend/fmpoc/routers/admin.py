"""2.0.0 administration on System/About: settings and organization name (#126), sessions (#127), diagnostics
(#128), health check (#129), maintenance mode (#130)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..services import admin_settings as adm
from ..services import diagnostics as diag
from ..services import maintenance as maint
from ..services import organization as org
from ..services import sessions as sess_svc
from .backup import _check_password

router = APIRouter(prefix="/api/system", tags=["administration"])


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsIn(In):
    changes: dict[str, Any] = Field(max_length=len(adm.EDITABLE))
    password: str | None = Field(default=None, max_length=256)
    confirmations: list[str] = Field(default_factory=list, max_length=10)


class BackupWarningIn(In):
    days: int


@router.get("/settings")
def settings_view(request: Request, ctx: Ctx = Depends(require("system.view"))):
    """#126: every setting with its value and source (Administrators and Auditors); the editor's state."""
    return adm.effective(request.app.state.settings, ctx.has("system.manage"))


@router.put("/settings")
def settings_save(body: SettingsIn, request: Request, db: Session = Depends(get_db),
                  ctx: Ctx = Depends(require("system.manage"))):
    out = adm.save(db, ctx, request.app.state.settings, body.changes, body.confirmations,
                   lambda: _check_password(request, db, ctx, body.password or "", "SERVER_SETTINGS"))
    db.commit()
    adm.apply_live(request.app, out.pop("live", {}))     # 2.3.0 (#379): the update channel applies at once
    return {**out, **adm.effective(request.app.state.settings, True)}


@router.get("/organization")
def organization_view(db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.about"))):
    """2.1.0 (#314): the organization profile (its own entity): name, address, phone, email, EIN. 2.2.0 (#349): read
    by the financial roles and Auditors too (System/About → General, read-only); only Administrators change it."""
    out = org.profile_out(db, ctx.workspace_id)
    db.commit()                      # ensure() may have created the entity
    return out


@router.put("/organization")
def organization(body: org.ProfileIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    """#126 the name; 2.1.0 (#314) the rest of the profile. Fields left out keep their value."""
    out = org.update(db, ctx, body)
    db.commit()
    return out


@router.get("/backup-age")
def backup_age(db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    return adm.backup_age(db, ctx.workspace_id)


@router.put("/backup-age")
def backup_age_set(body: BackupWarningIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    adm.set_backup_warning_days(db, ctx, body.days)
    db.commit()
    return adm.backup_age(db, ctx.workspace_id)


# ------------------------------------------------------------------ sessions (#127)
class EndUserIn(In):
    user_id: int


@router.get("/sessions")
def sessions_list(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.view"))):
    return {"sessions": sess_svc.active(db, request.app.state.settings, ctx), "can_end": ctx.has("system.manage")}


@router.post("/sessions/{ref}/end")
def session_end(ref: int, request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    sess_svc.end_one(db, request.app.state.settings, ctx, ref)
    db.commit()
    return {"ended": 1}


@router.post("/sessions/end-user")
def session_end_user(body: EndUserIn, request: Request, db: Session = Depends(get_db),
                     ctx: Ctx = Depends(require("system.manage"))):
    n = sess_svc.end_user(db, request.app.state.settings, ctx, body.user_id)
    db.commit()
    return {"ended": n}


@router.post("/sessions/end-all")
def session_end_all(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    n = sess_svc.end_everyone(db, request.app.state.settings, ctx)
    db.commit()
    return {"ended": n}


# ------------------------------------------------------------------ diagnostics (#128)
@router.post("/diagnostics")
def diagnostics(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    """A sanitized diagnostics file, generated on demand (Administrators only) and audited."""
    body, name = diag.build(db, request.app.state.settings, ctx)
    db.commit()
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store",
                             "X-Content-Type-Options": "nosniff"})


# ------------------------------------------------------------------ health check (#129)
@router.get("/health-check")
def health_check(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    """Sizes, free disk space and the migration state (no financial content)."""
    return diag.health(db, request.app.state.settings)


@router.post("/health-check/integrity")
def health_integrity(db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    out = diag.integrity_check(db, ctx)
    db.commit()
    return out


# ------------------------------------------------------------------ maintenance mode (#130)
class MaintenanceIn(In):
    on: bool
    message: str | None = Field(default=None, max_length=2000)
    starts_at: dt.datetime | None = None


@router.get("/maintenance")
def maintenance_get(db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    return maint.current(db)


@router.put("/maintenance")
def maintenance_set(body: MaintenanceIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    out = maint.turn_on(db, ctx, body.message or "", body.starts_at) if body.on else maint.turn_off(db, ctx)
    db.commit()
    return out


# ------------------------------------------------------------------ security overview (#131)
@router.get("/security-overview")
def security_overview(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.view"))):
    from ..services import security_overview as so
    return so.overview(db, request.app.state.settings, ctx.workspace_id, request.url.scheme == "https")
