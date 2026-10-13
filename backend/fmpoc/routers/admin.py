"""2.0.0 administration on System/About: settings and organization name (#126), sessions (#127), diagnostics (#128)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..services import admin_settings as adm
from ..services import diagnostics as diag
from ..services import sessions as sess_svc
from .backup import _check_password

router = APIRouter(prefix="/api/system", tags=["administration"])


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsIn(In):
    changes: dict[str, Any] = Field(max_length=len(adm.EDITABLE))
    password: str | None = Field(default=None, max_length=256)
    confirmations: list[str] = Field(default_factory=list, max_length=10)


class OrganizationIn(In):
    name: str = Field(max_length=adm.ORG_NAME_MAX * 2)


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
    return {**out, **adm.effective(request.app.state.settings, True)}


@router.put("/organization")
def organization(body: OrganizationIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    ws = adm.rename_organization(db, ctx, body.name)
    db.commit()
    return {"name": ws.name}


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
