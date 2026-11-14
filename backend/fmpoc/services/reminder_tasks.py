"""2.4.0 (#551): reminder tasks - a one-level checklist on a reminder (BR-REM-TASK-001..005, Kyle 2026-11-09).

- Every reminder has an **objective** task: always the last one (pinned), named by the reminder's title, able to carry
  a contact and an app function like a step. Ticking it resolves the reminder (Resolve… ticks it; Reopen unticks it).
  A reminder with only its objective looks and works as reminders always did.
- Steps (the tasks in front of the objective) are ticked in any order, once the reminder is shown, by whoever may
  resolve it; each tick records who and when. Ticking the last step doesn't resolve the reminder; the objective does.
- Completing with open steps needs a note; those steps stay unticked and are shown as skipped.
- Unticking a step of a resolved reminder reopens it (the Reopen rules apply).
- A task's contact is a fixed entity (ENTITY) or a position (POSITION): the active individuals holding it when the
  reminder is shown, compared without case or outer spaces. Nobody found, or an inactive fixed entity, shows the
  name or position without contact details - the signal to find the contact and edit the task.
- A task's app function is ``report:<id>`` (the report registry, services/report_prefs.REPORT_IDS) or ``page:<name>``;
  the UI labels it with the name users see (frontend/src/pages/reports/registry.ts, src/functions.ts).
- Tasks stay editable while the reminder is shown (the reminder's own fields don't); a ticked task can't be removed.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import AppError, validation
from ..models import Entity, Reminder, ReminderTask, utcnow
from .report_prefs import REPORT_IDS

MAX_TASKS = 25
# the pages a task can open (frontend/src/functions.ts PAGE_FUNCTIONS has the same ids, with the names users see)
PAGE_IDS = ("page:fiscal-years", "page:budgets", "page:bank-accounts", "page:register", "page:payments",
            "page:donations", "page:invoices", "page:entities", "page:events", "page:reports")
FUNCTION_IDS = frozenset({f"report:{r}" for r in REPORT_IDS} | set(PAGE_IDS))


def task_snapshot(t: ReminderTask) -> dict:
    return {"id": t.id, "title": t.title, "objective": bool(t.is_objective), "done": t.done_at is not None,
            "contact_kind": t.contact_kind, "contact_entity_id": t.contact_entity_id,
            "contact_position": t.contact_position, "function_id": t.function_id}


def _norm_position(p: str | None) -> str:
    return " ".join((p or "").split())


def _entity_ok(db: Session, ctx, entity_id: int | None) -> Entity | None:
    e = db.get(Entity, entity_id) if isinstance(entity_id, int) else None
    if e is None or e.workspace_id != ctx.workspace_id or e.is_system:
        return None
    return e


def _clean_item(db: Session, ctx, i: int | str, item, title_needed: bool = True) -> dict:
    title = (getattr(item, "title", None) or "").strip()
    if title_needed and not title:
        raise validation("Every task needs a name.", f"tasks.{i}.title")
    kind = item.contact_kind or None
    entity_id = position = None
    if kind == "ENTITY":
        if _entity_ok(db, ctx, item.contact_entity_id) is None:
            raise validation("The task's contact was not found.", f"tasks.{i}.contact_entity_id")
        entity_id = item.contact_entity_id
    elif kind == "POSITION":
        position = _norm_position(item.contact_position)
        if not position:
            raise validation("Choose the position the task's contact holds.", f"tasks.{i}.contact_position")
    fn = item.function_id or None
    if fn is not None and fn not in FUNCTION_IDS:
        raise validation("Choose an app function from the list.", f"tasks.{i}.function_id")
    return {"title": title, "contact_kind": kind, "contact_entity_id": entity_id, "contact_position": position,
            "function_id": fn}


def objective(r: Reminder) -> ReminderTask:
    """The reminder's objective task (created when missing - a new reminder), kept last and named by the title."""
    for t in r.tasks:
        if t.is_objective:
            break
    else:
        t = ReminderTask(is_objective=True, title=r.title)
        r.tasks.append(t)
    t.title = r.title
    return t


def steps(r: Reminder) -> list[ReminderTask]:
    return [t for t in r.tasks if not t.is_objective]


def set_tasks(db: Session, r: Reminder, ctx, items, objective_in=None) -> None:
    """Replace the steps with ``items`` (in order, in front of the objective) and, when given, the objective's contact
    and app function. Items with an ``id`` keep that step (and its tick); a ticked step left out is refused - untick
    it first. The objective is never removed or moved."""
    items = list(items or [])
    if len(items) + 1 > MAX_TASKS:
        raise validation(f"A reminder can have up to {MAX_TASKS} tasks (the steps and the reminder itself).", "tasks")
    obj = objective(r)
    current = {t.id: t for t in steps(r)}
    keep_ids = [it.id for it in items if it.id is not None]
    if len(keep_ids) != len(set(keep_ids)) or any(k not in current for k in keep_ids):
        raise validation("A task in the list isn't on this reminder; reload and try again.", "tasks")
    removed = [t for tid, t in current.items() if tid not in set(keep_ids)]
    if any(t.done_at is not None for t in removed):
        raise AppError(409, "REMINDER_TASK_DONE", "A completed task can't be removed; clear its completion first.")
    cleaned = [_clean_item(db, ctx, i, it) for i, it in enumerate(items)]
    if objective_in is not None:
        c = _clean_item(db, ctx, "objective", objective_in, title_needed=False)
        c.pop("title")
        for k, val in c.items():
            setattr(obj, k, val)
    ordered = []
    for seq, (it, c) in enumerate(zip(items, cleaned)):
        t = current[it.id] if it.id is not None else ReminderTask()
        for k, val in c.items():
            setattr(t, k, val)
        t.seq = seq
        ordered.append(t)
    obj.seq = len(ordered)
    r.tasks[:] = [*ordered, obj]


def copy_unticked(r: Reminder) -> list[ReminderTask]:
    return [ReminderTask(seq=t.seq, title=t.title, contact_kind=t.contact_kind, contact_entity_id=t.contact_entity_id,
                         contact_position=t.contact_position, function_id=t.function_id,
                         is_objective=t.is_objective) for t in r.tasks]


def open_steps(r: Reminder) -> list[ReminderTask]:
    return [t for t in steps(r) if t.done_at is None]


def get_task(r: Reminder, tid: int) -> ReminderTask:
    for t in r.tasks:
        if t.id == tid:
            return t
    raise AppError(404, "NOT_FOUND", "Task not found.")


def mark(t: ReminderTask, user_id: int | None) -> None:
    t.done_at, t.done_by_user_id = (utcnow(), user_id) if user_id is not None else (None, None)


# ------------------------------------------------------------------ shown contact details
def _person(e: Entity, details: bool) -> dict:
    from .checkprint.service import address_lines
    out = {"id": e.id, "name": e.display_name, "position": e.position or None, "active": bool(e.active)}
    if details and e.active:
        from .. import phone as phone_fmt
        out.update({"email": e.email or None, "phone": phone_fmt.display(e.phone) or None,
                    "address": address_lines(e)})
    return out


def holders(db: Session, ws_id: int, position: str) -> list[Entity]:
    key = _norm_position(position).lower()
    q = (select(Entity).where(Entity.workspace_id == ws_id, Entity.is_system.is_(False), Entity.active.is_(True),
                              Entity.entity_type == "INDIVIDUAL", Entity.position.is_not(None))
         .order_by(Entity.id))
    # outer spaces and case don't matter; inner runs of spaces count as one
    return [e for e in db.scalars(q) if _norm_position(e.position).lower() == key]


def contact_out(db: Session, ctx, t: ReminderTask) -> dict | None:
    details = ctx.has("register.view")
    if t.contact_kind == "ENTITY":
        e = _entity_ok(db, ctx, t.contact_entity_id)
        if e is None:
            return {"kind": "ENTITY", "label": None, "people": [], "missing": True}
        return {"kind": "ENTITY", "label": e.display_name, "inactive": not e.active, "people": [_person(e, details)],
                "missing": not e.active}
    if t.contact_kind == "POSITION":
        people = [_person(e, details) for e in holders(db, ctx.workspace_id, t.contact_position or "")]
        return {"kind": "POSITION", "label": t.contact_position, "people": people, "missing": not people,
                "several": len(people) > 1}
    return None


def tasks_out(db: Session, ctx, r: Reminder, name) -> list[dict]:
    """The steps, then the objective (always last)."""
    return [{**task_snapshot(t), "title": r.title if t.is_objective else t.title, "contact": contact_out(db, ctx, t),
             "done_at": t.done_at.isoformat() + "Z" if t.done_at else None,
             "done_by": name(t.done_by_user_id) if t.done_by_user_id else None} for t in r.tasks]
