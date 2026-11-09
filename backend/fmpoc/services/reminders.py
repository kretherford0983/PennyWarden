"""v1.6.3 CR-036: reminders and notifications (plan: project doc claude/freedger-plan-1.6.md).

- PERSONAL reminders: created by Budget Managers and Register Users; private to their owner.
- ORGANIZATION reminders: created/edited/deleted by Budget Managers; resolved or reopened by Budget Managers and
  Register Users; Budget Users and Auditors see the due, unresolved ones read-only. Administrators: none.
- One-time, date only (the server's local date). A reminder becomes a notification on its show date
  (due date - notify_days_before) and stays until someone resolves it, with an optional note.
- It can be edited or deleted only before its show date; afterwards it must be resolved (and can be reopened).
- Everything is audited.

1.6.7 - recurring ORGANIZATION reminders: "every N days / weeks / months / years", optionally until a date.
- Each occurrence is its own reminder with its own resolution note. Resolving one creates the next, due one
  interval after the *scheduled* due date (not the day it was resolved), unless "stop repeating" is chosen or the
  next due date would fall after the end date.
- Reopening a resolved occurrence removes the next one it created (it comes back when resolved again); that is
  refused once the next one has itself been resolved.
- Personal reminders do not repeat.

2.4.0 (#551) - tasks: a checklist on any reminder (services/reminder_tasks.py has the rules). Ticking the last open
task resolves the reminder; resolving with open tasks needs a note; tasks stay editable while the reminder is shown.
"""
from __future__ import annotations

import calendar
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, forbidden, not_found, validation
from ..models import BankAccount, Budget, FiscalYear, Reminder, User, utcnow
from . import bank_accounts as bank
from . import reminder_tasks as tasks_svc
from .common import budget_label

LINKS = {"FISCAL_YEAR": FiscalYear, "BUDGET": Budget, "BANK_ACCOUNT": BankAccount}


def today() -> dt.date:
    return dt.date.today()


def show_date(r: Reminder) -> dt.date:
    return r.due_date - dt.timedelta(days=r.notify_days_before or 0)


def is_due(r: Reminder, day: dt.date | None = None) -> bool:
    return show_date(r) <= (day or today())


UNIT_WORDS = {"DAY": "day", "WEEK": "week", "MONTH": "month", "YEAR": "year"}


def add_interval(anchor: dt.date, unit: str, n: int) -> dt.date:
    """anchor + n units. Months and years keep the anchor's day, clamped to the month's length (31 Jan -> 28 Feb)."""
    if unit == "DAY":
        return anchor + dt.timedelta(days=n)
    if unit == "WEEK":
        return anchor + dt.timedelta(weeks=n)
    months = anchor.month - 1 + n * (12 if unit == "YEAR" else 1)
    year, month = anchor.year + months // 12, months % 12 + 1
    return dt.date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def next_due(r: Reminder) -> dt.date | None:
    """Due date of the occurrence after this one, or None (does not repeat / the series has ended)."""
    if not r.repeat_every or not r.repeat_unit:
        return None
    try:
        nxt = add_interval(r.repeat_anchor or r.due_date, r.repeat_unit, r.repeat_every * ((r.repeat_index or 0) + 1))
    except (ValueError, OverflowError):
        return None
    return None if r.repeat_until and nxt > r.repeat_until else nxt


def repeat_label(r: Reminder) -> str | None:
    if not r.repeat_every or not r.repeat_unit:
        return None
    word = UNIT_WORDS[r.repeat_unit]
    text = f"Repeats every {word}" if r.repeat_every == 1 else f"Repeats every {r.repeat_every} {word}s"
    return text + (f" until {r.repeat_until.isoformat()}" if r.repeat_until else "")


def _link(db: Session, ctx, link_type: str | None, link_id: int | None) -> dict | None:
    if not link_type or link_id is None:
        return None
    obj = db.get(LINKS[link_type], link_id)
    if obj is None:
        return None
    if link_type == "FISCAL_YEAR":
        if obj.workspace_id != ctx.workspace_id:
            return None
        return {"type": link_type, "id": obj.id, "label": f"Fiscal Year {obj.display_name}", "url": f"/fiscal-years/{obj.id}"}
    if link_type == "BUDGET":
        fy = db.get(FiscalYear, obj.fiscal_year_id)
        if fy is None or fy.workspace_id != ctx.workspace_id or obj.is_budget_zero:
            return None
        parent = db.get(Budget, obj.parent_budget_id) if obj.parent_budget_id else None
        return {"type": link_type, "id": obj.id, "label": f"Budget {budget_label(obj, parent)} ({fy.display_name})", "url": "/budgets"}
    if obj.workspace_id != ctx.workspace_id:
        return None
    return {"type": link_type, "id": obj.id, "label": f"Bank account {obj.account_name} - {bank.masked(obj)}", "url": "/bank-accounts"}


def snapshot(r: Reminder) -> dict:
    return {"id": r.id, "scope": r.scope, "owner_user_id": r.owner_user_id, "title": r.title, "details": r.details,
            "due_date": r.due_date.isoformat(), "notify_days_before": r.notify_days_before, "link_type": r.link_type,
            "link_id": r.link_id, "resolved": r.resolved_at is not None, "resolution_note": r.resolution_note,
            "repeat_every": r.repeat_every, "repeat_unit": r.repeat_unit,
            "repeat_until": r.repeat_until.isoformat() if r.repeat_until else None,
            "tasks": [tasks_svc.task_snapshot(t) for t in r.tasks]}


def _can_resolve(ctx, r: Reminder) -> bool:
    return r.owner_user_id == ctx.user.id if r.scope == "PERSONAL" else ctx.has("reminder.org_resolve")


def _can_edit(ctx, r: Reminder) -> bool:
    return r.owner_user_id == ctx.user.id if r.scope == "PERSONAL" else ctx.has("reminder.org_manage")


def can_see(ctx, r: Reminder, day: dt.date | None = None) -> bool:
    if r.workspace_id != ctx.workspace_id or not ctx.has("reminder.view"):
        return False
    if r.scope == "PERSONAL":
        return r.owner_user_id == ctx.user.id
    if ctx.has("reminder.org_manage"):
        return True  # Budget Managers: upcoming, due and resolved
    if ctx.has("reminder.org_resolve"):
        return is_due(r, day)  # Register Users: due and resolved
    return is_due(r, day) and r.resolved_at is None  # Budget Users, Auditors: due and not yet cleared


def out(db: Session, ctx, r: Reminder, users: dict[int, str] | None = None) -> dict:
    day = today()
    def name(uid):
        return (users or {}).get(uid) or getattr(db.get(User, uid), "username", None)

    due = is_due(r, day)
    state = "RESOLVED" if r.resolved_at else ("DUE" if due else "UPCOMING")
    nxt = next_due(r)
    return {**snapshot(r), "state": state, "show_date": show_date(r).isoformat(),
            "repeat_label": repeat_label(r), "next_due": nxt.isoformat() if nxt else None,
            "overdue_days": max(0, (day - r.due_date).days) if state == "DUE" else 0,
            "owner": name(r.owner_user_id), "link": _link(db, ctx, r.link_type, r.link_id),
            "resolved_at": r.resolved_at.isoformat() + "Z" if r.resolved_at else None,
            "resolved_by": name(r.resolved_by_user_id) if r.resolved_by_user_id else None,
            "can_resolve": state == "DUE" and _can_resolve(ctx, r),
            "can_reopen": state == "RESOLVED" and _can_resolve(ctx, r),
            "can_edit": state == "UPCOMING" and _can_edit(ctx, r),
            # 2.4.0 (#551): the checklist; ticking while shown, task edits until resolved
            "tasks": tasks_svc.tasks_out(db, ctx, r, name),
            "tasks_done": sum(1 for t in r.tasks if t.done_at is not None),
            "can_tick": state == "DUE" and _can_resolve(ctx, r),
            "can_untick": state in ("DUE", "RESOLVED") and _can_resolve(ctx, r),
            "can_edit_tasks": state != "RESOLVED" and _can_edit(ctx, r)}


def _visible(db: Session, ctx) -> list[Reminder]:
    day = today()
    q = select(Reminder).where(Reminder.workspace_id == ctx.workspace_id).order_by(Reminder.due_date, Reminder.id)
    return [r for r in db.scalars(q) if can_see(ctx, r, day)]


def listing(db: Session, ctx, view: str) -> list[dict]:
    users = {u.id: u.username for u in db.scalars(select(User).where(User.workspace_id == ctx.workspace_id))}
    items = [out(db, ctx, r, users) for r in _visible(db, ctx)]
    want = {"due": "DUE", "upcoming": "UPCOMING", "resolved": "RESOLVED"}[view]
    items = [i for i in items if i["state"] == want]
    if view == "resolved":
        items.sort(key=lambda i: i["resolved_at"], reverse=True)
    return items


def due_count(db: Session, ctx) -> int:
    day = today()
    return sum(1 for r in _visible(db, ctx) if r.resolved_at is None and is_due(r, day))


def get(db: Session, ctx, rid: int) -> Reminder:
    r = db.get(Reminder, rid)
    if r is None or not can_see(ctx, r):
        raise not_found("Reminder")
    return r


def _apply(db: Session, ctx, r: Reminder, body) -> None:
    if (body.link_type is None) != (body.link_id is None):
        raise validation("Choose both what the reminder links to and the item, or neither.", "link_id")
    if body.link_type and _link(db, ctx, body.link_type, body.link_id) is None:
        raise validation("The linked item was not found.", "link_id")
    if (body.repeat_every is None) != (body.repeat_unit is None):
        raise validation("Choose both how often the reminder repeats and the unit, or neither.", "repeat_every")
    if body.repeat_every and r.scope != "ORGANIZATION":
        raise validation("Only organization reminders can repeat.", "repeat_every")
    if body.repeat_until and not body.repeat_every:
        raise validation("An end date needs a repeat interval.", "repeat_until")
    if body.repeat_until and body.repeat_until < body.due_date:
        raise validation("The end date cannot be before the due date.", "repeat_until")
    # keep the series' anchor while only the text changes; a new due date or interval starts the count again
    same_schedule = (r.repeat_anchor is not None and r.due_date == body.due_date
                     and r.repeat_every == body.repeat_every and r.repeat_unit == body.repeat_unit)
    r.title, r.details = body.title, body.details or None
    r.due_date, r.notify_days_before = body.due_date, body.notify_days_before
    r.repeat_every, r.repeat_unit, r.repeat_until = body.repeat_every, body.repeat_unit, body.repeat_until
    if not body.repeat_every:
        r.repeat_anchor, r.repeat_index = None, 0
    elif not same_schedule:
        r.repeat_anchor, r.repeat_index = body.due_date, 0
    r.link_type, r.link_id = body.link_type, body.link_id
    if body.tasks is not None:           # 2.4.0 (#551): omitted = the checklist is left as it is
        tasks_svc.set_tasks(db, r, ctx, body.tasks)
    r.updated_by_user_id = ctx.user.id


def create(db: Session, ctx, body) -> Reminder:
    ctx.require("reminder.org_manage" if body.scope == "ORGANIZATION" else "reminder.personal")
    r = Reminder(workspace_id=ctx.workspace_id, scope=body.scope, owner_user_id=ctx.user.id)
    _apply(db, ctx, r, body)
    db.add(r)
    db.flush()
    audit.record(db, ctx, "REMINDER_CREATED", "reminder", r.id, None, snapshot(r))
    return r


def _editable(ctx, r: Reminder) -> None:
    if not _can_edit(ctx, r):
        raise forbidden()
    if r.resolved_at is not None or is_due(r):
        raise AppError(409, "REMINDER_DUE", "A reminder can only be changed or deleted before it is shown. "
                       "Resolve it instead (a resolved reminder can be reopened).")


def update(db: Session, ctx, r: Reminder, body) -> Reminder:
    _editable(ctx, r)
    if body.scope != r.scope:
        raise validation("A reminder cannot be switched between personal and organization.", "scope")
    before = snapshot(r)
    _apply(db, ctx, r, body)
    db.flush()
    if snapshot(r) != before:
        audit.record(db, ctx, "REMINDER_UPDATED", "reminder", r.id, before, snapshot(r))
    return r


def delete(db: Session, ctx, r: Reminder) -> None:
    _editable(ctx, r)
    audit.record(db, ctx, "REMINDER_DELETED", "reminder", r.id, snapshot(r), None)
    db.delete(r)


def _next_of(db: Session, r: Reminder) -> Reminder | None:
    return db.scalars(select(Reminder).where(Reminder.repeat_source_id == r.id).order_by(Reminder.id)).first()


def _create_next(db: Session, ctx, r: Reminder) -> Reminder | None:
    due = next_due(r)
    if due is None or _next_of(db, r) is not None:
        return None
    n = Reminder(workspace_id=r.workspace_id, scope=r.scope, owner_user_id=r.owner_user_id, title=r.title,
                 details=r.details, due_date=due, notify_days_before=r.notify_days_before, link_type=r.link_type,
                 link_id=r.link_id, repeat_every=r.repeat_every, repeat_unit=r.repeat_unit,
                 repeat_until=r.repeat_until, repeat_anchor=r.repeat_anchor or r.due_date,
                 repeat_index=(r.repeat_index or 0) + 1, repeat_source_id=r.id, updated_by_user_id=ctx.user.id,
                 tasks=tasks_svc.copy_unticked(r))       # 2.4.0 (#551): the same checklist, nothing ticked
    db.add(n)
    db.flush()
    audit.record(db, ctx, "REMINDER_CREATED", "reminder", n.id, None, {**snapshot(n), "repeat_of": r.id})
    return n


def resolve(db: Session, ctx, r: Reminder, note: str | None, stop_repeating: bool = False) -> Reminder:
    if not _can_resolve(ctx, r):
        raise forbidden()
    if r.resolved_at is not None:
        raise AppError(409, "INVALID_STATE", "This reminder is already resolved.")
    if not is_due(r):
        raise AppError(409, "REMINDER_NOT_DUE", "This reminder is not due yet; edit or delete it instead.")
    if tasks_svc.open_tasks(r) and not (note or "").strip():   # 2.4.0 (#551): open tasks are kept as skipped
        raise validation("Some tasks aren't ticked: add a note saying why the reminder is resolved anyway.", "note")
    before = snapshot(r)
    r.resolved_at, r.resolved_by_user_id, r.resolution_note = utcnow(), ctx.user.id, (note or "").strip() or None
    db.flush()
    audit.record(db, ctx, "REMINDER_RESOLVED", "reminder", r.id, before, snapshot(r))
    if not stop_repeating:
        _create_next(db, ctx, r)
    return r


def reopen(db: Session, ctx, r: Reminder) -> Reminder:
    if not _can_resolve(ctx, r):
        raise forbidden()
    if r.resolved_at is None:
        raise AppError(409, "INVALID_STATE", "This reminder is not resolved.")
    nxt = _next_of(db, r)
    if nxt is not None:
        if nxt.resolved_at is not None:
            raise AppError(409, "REMINDER_NEXT_RESOLVED", "This reminder repeats and its next occurrence has already "
                           "been resolved, so it can no longer be reopened.")
        audit.record(db, ctx, "REMINDER_DELETED", "reminder", nxt.id, {**snapshot(nxt), "repeat_of": r.id}, None)
        db.delete(nxt)
    before = snapshot(r)
    r.resolved_at = r.resolved_by_user_id = r.resolution_note = None
    db.flush()
    audit.record(db, ctx, "REMINDER_REOPENED", "reminder", r.id, before, snapshot(r))
    return r


# ------------------------------------------------------------------ 2.4.0 (#551) tasks
def update_tasks(db: Session, ctx, r: Reminder, items) -> Reminder:
    """BR-REM-TASK-005: the checklist (and each task's contact and app function) stays editable while the reminder is
    shown, by whoever may edit the reminder; the reminder's own fields stay locked. Not once it is resolved."""
    if not _can_edit(ctx, r):
        raise forbidden()
    if r.resolved_at is not None:
        raise AppError(409, "INVALID_STATE", "This reminder is resolved; reopen it to change its tasks.")
    before = snapshot(r)
    tasks_svc.set_tasks(db, r, ctx, items)
    r.updated_by_user_id = ctx.user.id
    db.flush()
    if snapshot(r) != before:
        audit.record(db, ctx, "REMINDER_UPDATED", "reminder", r.id, before, snapshot(r))
    return r


def tick(db: Session, ctx, r: Reminder, tid: int, note: str | None = None) -> Reminder:
    """BR-REM-TASK-001/002: tick one task; the last open one resolves the reminder."""
    if not _can_resolve(ctx, r):
        raise forbidden()
    if r.resolved_at is not None:
        raise AppError(409, "INVALID_STATE", "This reminder is already resolved.")
    if not is_due(r):
        raise AppError(409, "REMINDER_NOT_DUE", "This reminder isn't shown yet, so its tasks can't be ticked.")
    t = tasks_svc.get_task(r, tid)
    if t.done_at is not None:
        raise AppError(409, "INVALID_STATE", "This task is already ticked.")
    tasks_svc.mark(t, ctx.user.id)
    db.flush()
    audit.record(db, ctx, "REMINDER_TASK_TICKED", "reminder", r.id, None,
                 {"reminder_id": r.id, "task": tasks_svc.task_snapshot(t)})
    if not tasks_svc.open_tasks(r):
        resolve(db, ctx, r, note)
    return r


def untick(db: Session, ctx, r: Reminder, tid: int) -> Reminder:
    """BR-REM-TASK-002: unticking a task of a resolved reminder reopens it (refused as Reopen is)."""
    if not _can_resolve(ctx, r):
        raise forbidden()
    t = tasks_svc.get_task(r, tid)
    if t.done_at is None:
        raise AppError(409, "INVALID_STATE", "This task isn't ticked.")
    if r.resolved_at is not None:
        reopen(db, ctx, r)
    before = tasks_svc.task_snapshot(t)
    tasks_svc.mark(t, None)
    db.flush()
    audit.record(db, ctx, "REMINDER_TASK_UNTICKED", "reminder", r.id, {"reminder_id": r.id, "task": before},
                 {"reminder_id": r.id, "task": tasks_svc.task_snapshot(t)})
    return r
