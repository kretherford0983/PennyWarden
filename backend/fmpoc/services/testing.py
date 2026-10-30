"""2.2.0 (#231): testing mode - a test server where an Administrator can move timers and schedules instead of waiting.

Decisions (Kyle, 2026-10-14 and 2026-10-24):

* Turned on only by the server owner: ``testing_mode = true`` in ``config.toml`` (or FM_TESTING_MODE), never from the
  web. Production builds allow it too (the use case: the released app installed a second time as a test server).
  **Server installs only** - a local install ignores the setting (phase 2).
* While on: a banner on every page; System/About -> **Testing** for Administrators with: the next scheduled backup (or
  *as if due now*); **retry the failed backup now**; **back-date a backup run** (to try retention, which counts by the
  runs' start times); the **time of the last successful backup** (the backup-age warning); **clear the reinitialize
  cooldown**; **move a reminder's due date**; **force the update check**.
* **No global fake clock**: transaction dates, audit timestamps, sessions and two-step codes keep the real time.
* **No hard deletes** in 2.2.0 (#319's Data-only restore resets test data).
* Every testing action is still recorded, as ``TESTING_*`` events in the Security category.
* Backups made in testing mode are marked; the app refuses to restore one onto a server that is not in testing mode
  (the command line allows it with ``--accept-testing-backup``).
* With testing mode off the Testing endpoints don't exist (404).
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, conflict, not_found, validation
from ..models import BackupRun, BackupSchedule, Reminder, TestingState, utcnow

log = logging.getLogger("fmpoc")

# The running server's testing mode, set by create_app (services read it without the settings at hand). The overrides
# in testing_state are only read while it is on.
ENABLED = False
MAX_BACKDATE_DAYS = 3660


def configure(settings) -> bool:
    global ENABLED
    on = bool(getattr(settings, "testing_mode", False))
    if on and settings.mode != "server":
        log.warning("testing_mode is set but ignored: testing mode is for server installs only.")
        on = False
    if on:
        log.warning("TESTING MODE is on: this server is for test data only.")
    ENABLED = on
    return on


def enabled_for(settings) -> bool:
    return bool(getattr(settings, "testing_mode", False)) and settings.mode == "server"


def require(app) -> None:
    """The Testing endpoints don't exist with testing mode off."""
    if not getattr(app.state, "testing_mode", False):
        raise AppError(404, "NOT_FOUND", "Not found.")


def _state(db: Session, ws_id: int, create: bool = False) -> TestingState | None:
    s = db.scalar(select(TestingState).where(TestingState.workspace_id == ws_id))
    if s is None and create:
        s = TestingState(workspace_id=ws_id)
        db.add(s)
        db.flush()
    return s


# ------------------------------------------------------------------ read by the rest of the application
def last_backup_override(db: Session, ws_id: int) -> dt.datetime | None:
    if not ENABLED:
        return None
    s = _state(db, ws_id)
    return s.last_backup_at if s else None


def cooldown_cleared_at(db: Session, ws_id: int) -> dt.datetime | None:
    if not ENABLED:
        return None
    s = _state(db, ws_id)
    return s.reinitialize_cooldown_cleared_at if s else None


# ------------------------------------------------------------------ the Testing tab
def _iso(d: dt.datetime | None) -> str | None:
    return d.isoformat(timespec="seconds") + "Z" if d else None


def view(db: Session, ctx, settings) -> dict:
    from . import admin_settings as adm
    from . import reinitialize as reinit
    from . import scheduled_backup as sb
    s = sb.get(db, ctx.workspace_id)
    st = _state(db, ctx.workspace_id)
    runs = list(db.scalars(select(BackupRun).where(BackupRun.workspace_id == ctx.workspace_id)
                           .order_by(BackupRun.started_at.desc(), BackupRun.id.desc()).limit(20)))
    reminders = list(db.scalars(select(Reminder).where(Reminder.workspace_id == ctx.workspace_id,
                                                       Reminder.resolved_at.is_(None),
                                                       Reminder.scope == "ORGANIZATION")
                                .order_by(Reminder.due_date, Reminder.id).limit(50)))
    from . import updates
    up = updates.status(db, settings)
    return {
        "testing_mode": True, "now": _iso(utcnow()),
        "schedule": {"enabled": bool(s and s.enabled), "ready": bool(s and s.public_key and s.destination),
                     "next_run_at": _iso(s.next_run_at) if s else None, "retry_at": _iso(s.retry_at) if s else None},
        "runs": [{"id": r.id, "started_at": _iso(r.started_at), "result": r.result, "trigger": r.trigger,
                  "filename": r.filename, "removed": r.deleted_at is not None} for r in runs],
        "last_backup_at": _iso(adm.last_backup_at(db, ctx.workspace_id)),
        "last_backup_overridden": bool(st and st.last_backup_at),
        "backup_age": adm.backup_age(db, ctx.workspace_id),
        "reinitialize_cooldown_until": _iso(reinit.cooldown_until(db, ctx.workspace_id)),
        "reminders": [{"id": r.id, "title": r.title, "due_date": r.due_date.isoformat(),
                       "repeats": bool(r.repeat_every)} for r in reminders],
        "update_check": {"checked_at": up.get("checked_at"), "enabled": up.get("enabled")},
    }


def _record(db, ctx, action: str, before, after) -> None:
    audit.record(db, ctx, action, "workspace", ctx.workspace_id, before, {**(after or {}), "testing_mode": True},
                 category="SECURITY")


def _naive_utc(when: dt.datetime) -> dt.datetime:
    if when.tzinfo is not None:
        when = when.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return when


def set_next_backup(db: Session, ctx, when: dt.datetime | None, now_due: bool) -> None:
    from . import scheduled_backup as sb
    s = sb.get(db, ctx.workspace_id)
    if s is None or not s.enabled or not s.public_key:
        raise conflict("NO_SCHEDULE", "Turn scheduled backups on first (Backups → Scheduled).")
    before = {"next_run_at": _iso(s.next_run_at)}
    if now_due:
        s.next_run_at = utcnow()
    else:
        if when is None:
            raise validation("Choose the date and time of the next scheduled backup.", "next_run_at")
        s.next_run_at = _naive_utc(when)
    _record(db, ctx, "TESTING_BACKUP_SCHEDULE_MOVED", before, {"next_run_at": _iso(s.next_run_at), "due_now": now_due})


def retry_now(db: Session, ctx) -> None:
    from . import scheduled_backup as sb
    s = sb.get(db, ctx.workspace_id)
    if s is None or s.retry_at is None:
        raise conflict("NO_RETRY", "No failed backup is waiting for a retry.")
    before = {"retry_at": _iso(s.retry_at)}
    s.retry_at = utcnow()
    _record(db, ctx, "TESTING_BACKUP_RETRY_NOW", before, {"retry_at": _iso(s.retry_at)})


def backdate_run(db: Session, ctx, run_id: int, days: int) -> None:
    """Retention counts by the runs' start times, so moving a run back tries daily / weekly / monthly keeping."""
    if not 1 <= days <= MAX_BACKDATE_DAYS:
        raise validation(f"Days: 1 to {MAX_BACKDATE_DAYS}.", "days")
    r = db.get(BackupRun, run_id)
    if r is None or r.workspace_id != ctx.workspace_id:
        raise not_found("Backup run")
    before = {"run_id": r.id, "started_at": _iso(r.started_at)}
    delta = dt.timedelta(days=days)
    r.started_at = r.started_at - delta
    if r.finished_at:
        r.finished_at = r.finished_at - delta
    _record(db, ctx, "TESTING_BACKUP_RUN_BACKDATED", before, {"run_id": r.id, "started_at": _iso(r.started_at),
                                                               "days": days})


def set_last_backup(db: Session, ctx, when: dt.datetime | None) -> None:
    st = _state(db, ctx.workspace_id, create=True)
    before = {"last_backup_at": _iso(st.last_backup_at)}
    st.last_backup_at = _naive_utc(when) if when else None
    st.updated_at = utcnow()
    _record(db, ctx, "TESTING_LAST_BACKUP_SET", before, {"last_backup_at": _iso(st.last_backup_at)})


def clear_reinitialize_cooldown(db: Session, ctx) -> None:
    from . import reinitialize as reinit
    until = reinit.cooldown_until(db, ctx.workspace_id)
    if until is None:
        raise conflict("NO_COOLDOWN", "There is no reinitialize cooldown to clear.")
    st = _state(db, ctx.workspace_id, create=True)
    st.reinitialize_cooldown_cleared_at = st.updated_at = utcnow()
    _record(db, ctx, "TESTING_REINITIALIZE_COOLDOWN_CLEARED", {"cooldown_until": _iso(until)}, {"cooldown_until": None})


def move_reminder(db: Session, ctx, reminder_id: int, due: dt.date) -> None:
    r = db.get(Reminder, reminder_id)
    if r is None or r.workspace_id != ctx.workspace_id or r.scope != "ORGANIZATION":
        raise not_found("Reminder")
    if r.resolved_at is not None:
        raise conflict("REMINDER_RESOLVED", "This reminder is resolved.")
    before = {"reminder_id": r.id, "due_date": r.due_date.isoformat()}
    if r.repeat_anchor is not None and r.repeat_index == 0:
        r.repeat_anchor = due        # the first of a series: the series counts from the new date
    r.due_date = due
    _record(db, ctx, "TESTING_REMINDER_MOVED", before, {"reminder_id": r.id, "due_date": due.isoformat()})


def force_update_check(app, db: Session, ctx) -> dict:
    from . import updates
    made = updates.check(app, force=True)
    _record(db, ctx, "TESTING_UPDATE_CHECK_FORCED", None, {"request_made": made})
    return {"request_made": made}
