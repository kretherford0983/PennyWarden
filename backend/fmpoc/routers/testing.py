"""2.2.0 (#231): System/About -> Testing (testing mode only; 404 otherwise). Administrators (system.manage)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..services import testing as svc

router = APIRouter(prefix="/api/system/testing", tags=["testing"])


def _on(request: Request) -> None:
    svc.require(request.app)


class NextBackupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    next_run_at: dt.datetime | None = None
    due_now: bool = False


class LastBackupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    last_backup_at: dt.datetime | None = None      # null = back to the real last backup


class BackdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(ge=1, le=svc.MAX_BACKDATE_DAYS)


class ReminderDueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    due_date: dt.date


@router.get("", dependencies=[Depends(_on)])
def view(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    return svc.view(db, ctx, request.app.state.settings)


def _done(request, db, ctx):
    db.commit()
    return svc.view(db, ctx, request.app.state.settings)


@router.post("/backup-schedule", dependencies=[Depends(_on)])
def next_backup(body: NextBackupIn, request: Request, db: Session = Depends(get_db),
                ctx: Ctx = Depends(require("system.manage"))):
    svc.set_next_backup(db, ctx, body.next_run_at, body.due_now)
    return _done(request, db, ctx)


@router.post("/backup-retry", dependencies=[Depends(_on)])
def retry(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    svc.retry_now(db, ctx)
    return _done(request, db, ctx)


@router.post("/backup-runs/{run_id}/backdate", dependencies=[Depends(_on)])
def backdate(run_id: int, body: BackdateIn, request: Request, db: Session = Depends(get_db),
             ctx: Ctx = Depends(require("system.manage"))):
    svc.backdate_run(db, ctx, run_id, body.days)
    return _done(request, db, ctx)


@router.post("/last-backup", dependencies=[Depends(_on)])
def last_backup(body: LastBackupIn, request: Request, db: Session = Depends(get_db),
                ctx: Ctx = Depends(require("system.manage"))):
    svc.set_last_backup(db, ctx, body.last_backup_at)
    return _done(request, db, ctx)


@router.post("/reinitialize-cooldown/clear", dependencies=[Depends(_on)])
def clear_cooldown(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    svc.clear_reinitialize_cooldown(db, ctx)
    return _done(request, db, ctx)


@router.post("/reminders/{reminder_id}/due-date", dependencies=[Depends(_on)])
def reminder_due(reminder_id: int, body: ReminderDueIn, request: Request, db: Session = Depends(get_db),
                 ctx: Ctx = Depends(require("system.manage"))):
    svc.move_reminder(db, ctx, reminder_id, body.due_date)
    return _done(request, db, ctx)


@router.post("/update-check", dependencies=[Depends(_on)])
def update_check(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    out = svc.force_update_check(request.app, db, ctx)
    db.commit()
    return {**svc.view(db, ctx, request.app.state.settings), **out}
