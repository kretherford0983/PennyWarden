"""2.0.0 administration on System/About: settings and organization name (#126)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..services import admin_settings as adm
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
