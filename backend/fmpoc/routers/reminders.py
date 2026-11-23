"""v1.6.3 CR-036: reminders and notifications API."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..schemas import ReminderIn, ReminderResolutionLinkIn, ReminderResolveIn, ReminderTasksIn, ReminderTickIn
from ..services import reminders as svc

router = APIRouter(prefix="/api/reminders", tags=["reminders"])
viewer = require("reminder.view")


@router.get("")
def list_reminders(view: Literal["due", "upcoming", "resolved"] = "due", db: Session = Depends(get_db),
                   ctx: Ctx = Depends(viewer)):
    return svc.listing(db, ctx, view)


@router.get("/resolution-link-options")
def resolution_link_options(kind: Literal["TRANSACTION", "EVENT"], q: str | None = None, db: Session = Depends(get_db),
                            ctx: Ctx = Depends(viewer)):
    """2.5.0 (#594): candidates for "what resolved it" (transactions need Register access, events the module)."""
    return svc.resolution_link_options(db, ctx, kind, (q or "")[:100])


@router.get("/count")
def count(db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    return {"due": svc.due_count(db, ctx)}


@router.post("", status_code=201)
def create(body: ReminderIn, db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    r = svc.create(db, ctx, body)
    db.commit()
    return svc.out(db, ctx, r)


@router.put("/{rid}")
def update(rid: int, body: ReminderIn, db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    r = svc.update(db, ctx, svc.get(db, ctx, rid), body)
    db.commit()
    return svc.out(db, ctx, r)


@router.delete("/{rid}")
def delete(rid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    svc.delete(db, ctx, svc.get(db, ctx, rid))
    db.commit()
    return {"deleted": True}


@router.post("/{rid}/resolve")
def resolve(rid: int, body: ReminderResolveIn, db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    r = svc.resolve(db, ctx, svc.get(db, ctx, rid), body.note, body.stop_repeating,
                    body.resolution_link_type, body.resolution_link_id)
    db.commit()
    return svc.out(db, ctx, r)


@router.put("/{rid}/resolution-link")
def resolution_link(rid: int, body: ReminderResolutionLinkIn, db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    """2.5.0 (#594): add, change or remove what resolved a resolved reminder."""
    r = svc.set_resolution_link(db, ctx, svc.get(db, ctx, rid), body.resolution_link_type, body.resolution_link_id)
    db.commit()
    return svc.out(db, ctx, r)


@router.post("/{rid}/reopen")
def reopen(rid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    r = svc.reopen(db, ctx, svc.get(db, ctx, rid))
    db.commit()
    return svc.out(db, ctx, r)


# 2.4.0 (#551): the checklist
@router.put("/{rid}/tasks")
def update_tasks(rid: int, body: ReminderTasksIn, db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    r = svc.update_tasks(db, ctx, svc.get(db, ctx, rid), body.tasks, body.objective)
    db.commit()
    return svc.out(db, ctx, r)


@router.post("/{rid}/tasks/{tid}/tick")
def tick(rid: int, tid: int, body: ReminderTickIn, db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    r = svc.tick(db, ctx, svc.get(db, ctx, rid), tid, body.note)
    db.commit()
    return svc.out(db, ctx, r)


@router.post("/{rid}/tasks/{tid}/untick")
def untick(rid: int, tid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(viewer)):
    r = svc.untick(db, ctx, svc.get(db, ctx, rid), tid)
    db.commit()
    return svc.out(db, ctx, r)
