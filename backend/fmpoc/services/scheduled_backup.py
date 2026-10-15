"""1.9.0 (#62): scheduled automatic backups.

An Administrator chooses Daily (at a time) or Weekly (a day and a time), server local time; one destination folder the
operating system can already see (server: one of `backup_folders` in config.toml; local: any folder the app can write
to); a backup passphrase that protects a key pair (services/backup.new_keypair: the application keeps only what locks a
backup); and how many daily / weekly / monthly backups to keep. A background thread (started with the web server, see
app.py) checks every 30 seconds. A failed backup is retried after 1, 2, 4 ... hours (at most 24); the next scheduled
backup runs at its time regardless and starts the sequence again. A backup missed while the app was not running runs
at the next start. Retention only ever deletes files recorded as written by a successful run in this folder.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import secrets
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from .. import audit
from ..config import backup_folders
from ..errors import AppError, conflict, validation
from ..models import BackupRun, BackupSchedule, utcnow
from . import backup as bk

log = logging.getLogger("fmpoc")

TICK_SECONDS = 30
FIRST_TICK_SECONDS = 60          # after a start, give the application a minute before a missed backup runs
RETRY_FIRST_MINUTES = 60
RETRY_MAX_MINUTES = 24 * 60
MISSED_AFTER_MINUTES = 15        # later than this after its time, a scheduled backup counts as missed
MAX_KEEP = 366
HISTORY = 30
FILE_RE = re.compile(r"^[a-z0-9]+-backup-[a-z0-9-]+-\d{8}-\d{6}(-\d+)?\.fmbak$")
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_run_lock = threading.Lock()


# ------------------------------------------------------------------ time (server local time for the schedule)
def _to_utc(local_naive: dt.datetime) -> dt.datetime:
    return local_naive.astimezone(dt.timezone.utc).replace(tzinfo=None)


def _to_local(utc_naive: dt.datetime) -> dt.datetime:
    return utc_naive.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)


def next_run(s: BackupSchedule, after_utc: dt.datetime) -> dt.datetime:
    """The first scheduled time strictly after `after_utc` (UTC naive)."""
    after = _to_local(after_utc)
    hh, mm = (int(x) for x in s.time_of_day.split(":"))
    cand = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if s.frequency == "WEEKLY":
        cand += dt.timedelta(days=(s.weekday - cand.weekday()) % 7)
        if cand <= after:
            cand += dt.timedelta(days=7)
    elif cand <= after:
        cand += dt.timedelta(days=1)
    return _to_utc(cand)


def _iso(d: dt.datetime | None) -> str | None:
    return d.isoformat() + "Z" if d else None


def _local_text(d: dt.datetime | None) -> str | None:
    return _to_local(d).strftime("%Y-%m-%d %H:%M") if d else None


# ------------------------------------------------------------------ settings
def get(db, ws_id: int) -> BackupSchedule | None:
    return db.scalar(select(BackupSchedule).where(BackupSchedule.workspace_id == ws_id))


def snapshot(s: BackupSchedule | None) -> dict:
    if s is None:
        return {}
    return {"enabled": s.enabled, "frequency": s.frequency, "weekday": s.weekday, "time_of_day": s.time_of_day,
            "destination": s.destination, "keep_daily": s.keep_daily, "keep_weekly": s.keep_weekly,
            "keep_monthly": s.keep_monthly, "key_fingerprint": s.key_fingerprint}


def failing(s: BackupSchedule | None) -> bool:
    return bool(s and s.last_failure_at and (s.last_success_at is None or s.last_failure_at > s.last_success_at))


def alert(db, ws_id: int) -> dict:
    s = get(db, ws_id)
    if not failing(s):
        return {"failed": False}
    when = s.retry_at if s.enabled else None
    return {"failed": True, "failed_at": _iso(s.last_failure_at), "error": s.last_error,
            "message": f"The last scheduled backup failed on {_local_text(s.last_failure_at)}: {s.last_error}"
                       + (f" It is tried again at {_local_text(when)}." if when else "")}


def out(db, settings, ws_id: int) -> dict:
    s = get(db, ws_id)
    runs = list(db.scalars(select(BackupRun).where(BackupRun.workspace_id == ws_id)
                           .order_by(BackupRun.started_at.desc(), BackupRun.id.desc()).limit(HISTORY)))
    base = snapshot(s) if s else {"enabled": False, "frequency": "DAILY", "weekday": 0, "time_of_day": "02:00",
                                  "destination": None, "keep_daily": 7, "keep_weekly": 4, "keep_monthly": 6,
                                  "key_fingerprint": None}
    return {**base, "mode": settings.mode, "allowed_folders": backup_folders(settings) if settings.mode == "server" else None,
            "passphrase_set": bool(s and s.public_key), "passphrase_set_at": _iso(s.passphrase_set_at) if s else None,
            "next_run_at": _iso(s.next_run_at) if s and s.enabled else None,
            "next_run_local": _local_text(s.next_run_at) if s and s.enabled else None,
            "retry_at": _iso(s.retry_at) if s and s.enabled else None,
            "retry_local": _local_text(s.retry_at) if s and s.enabled else None,
            "last_success_at": _iso(s.last_success_at) if s else None,
            "last_failure_at": _iso(s.last_failure_at) if s else None, "last_error": s.last_error if s else None,
            "alert": alert(db, ws_id), "timezone": dt.datetime.now().astimezone().tzname(),
            "history": [{"id": r.id, "trigger": r.trigger, "started_at": _iso(r.started_at),
                         "started_local": _local_text(r.started_at), "finished_at": _iso(r.finished_at),
                         "result": r.result, "filename": r.filename, "size": r.size, "error": r.error,
                         "deleted": r.deleted_at is not None} for r in runs]}


def check_destination(settings, path: str | None) -> str:
    p = (path or "").strip()
    if not p:
        raise validation("Choose the folder the backups are written to.", "destination")
    if settings.mode == "server":
        allowed = backup_folders(settings)
        if not allowed:
            raise validation("No backup folders are configured on this server. The server owner lists them as "
                             "backup_folders in config.toml.", "destination")
        # Return the server owner's configured folder, never the submitted text: in server mode the destination is
        # always a value from config.toml (CodeQL py/path-injection, #9-#6).
        match = next((a for a in allowed if os.path.normpath(a) == os.path.normpath(p)), None)
        if match is None:
            raise validation("Choose one of the backup folders configured on this server.", "destination")
        return match
    if not os.path.isabs(p):
        raise validation("Enter the full path of the folder (for example D:\\Backups or /Volumes/Backup).",
                         "destination")
    if not Path(p).is_dir():
        raise validation("That folder does not exist or cannot be reached.", "destination")
    return p


def test_folder(settings, path: str | None) -> dict:
    p = check_destination(settings, path)
    probe = Path(p) / f".pennywarden-write-test-{secrets.token_hex(4)}"
    try:
        probe.write_bytes(b"PennyWarden write test - safe to delete\n")
        probe.unlink()
        return {"ok": True, "destination": p, "message": f"The folder {p} can be written to."}
    except OSError as e:
        try:
            probe.unlink()
        except OSError:
            pass
        return {"ok": False, "destination": p, "message": f"The folder {p} cannot be written to ({e.strerror or type(e).__name__})."}


def _count(v, name: str) -> int:
    if v is None:
        return 0
    if not isinstance(v, int) or v < 0 or v > MAX_KEEP:
        raise validation(f"Enter a number from 0 to {MAX_KEEP}.", name)
    return v


def save(db, settings, ctx, data) -> BackupSchedule:
    s = get(db, ctx.workspace_id)
    before = snapshot(s)
    if s is None:
        s = BackupSchedule(workspace_id=ctx.workspace_id)
        db.add(s)
    if data.frequency not in ("DAILY", "WEEKLY"):
        raise validation("Choose Daily or Weekly.", "frequency")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", data.time_of_day or ""):
        raise validation("Enter a time as HH:MM (24-hour).", "time_of_day")
    if data.frequency == "WEEKLY" and not (isinstance(data.weekday, int) and 0 <= data.weekday <= 6):
        raise validation("Choose a day of the week.", "weekday")
    daily = _count(data.keep_daily, "keep_daily") if data.frequency == "DAILY" else 0
    weekly, monthly = _count(data.keep_weekly, "keep_weekly"), _count(data.keep_monthly, "keep_monthly")
    if daily + weekly + monthly < 1:
        raise validation("Keep at least one backup.", "keep_daily" if data.frequency == "DAILY" else "keep_weekly")
    dest = check_destination(settings, data.destination) if (data.destination or data.enabled) else None
    if data.passphrase:
        if len(data.passphrase) < bk.MIN_PASSPHRASE:
            raise validation(f"The backup passphrase must be at least {bk.MIN_PASSPHRASE} characters.", "passphrase")
        if data.passphrase != data.passphrase_confirmation:
            raise validation("The passphrase and its confirmation do not match.", "passphrase_confirmation")
        kp = bk.new_keypair(data.passphrase)
        s.public_key, s.wrapped_private_key, s.key_fingerprint = kp["public_key"], kp["wrapped_private_key"], kp["fingerprint"]
        s.passphrase_set_at = utcnow()
        audit.record(db, ctx, "BACKUP_PASSPHRASE_SET", "workspace", ctx.workspace_id,
                     {"key_fingerprint": before.get("key_fingerprint")}, {"key_fingerprint": kp["fingerprint"]},
                     category="SECURITY")
    if data.enabled and not s.public_key:
        raise validation("Set a backup passphrase before turning scheduled backups on.", "passphrase")
    timing_changed = (s.frequency, s.weekday, s.time_of_day) != (data.frequency, data.weekday or 0, data.time_of_day)
    s.frequency, s.weekday, s.time_of_day = data.frequency, data.weekday or 0, data.time_of_day
    s.destination, s.keep_daily, s.keep_weekly, s.keep_monthly = dest, daily, weekly, monthly
    was_enabled = bool(before.get("enabled"))
    s.enabled = bool(data.enabled)
    if s.enabled and (not was_enabled or timing_changed or s.next_run_at is None):
        s.next_run_at = next_run(s, utcnow())
    if not s.enabled:
        s.next_run_at = s.retry_at = s.retry_wait_minutes = None
    s.updated_at, s.updated_by_user_id = utcnow(), ctx.user.id
    after = snapshot(s)
    if after != before:
        audit.record(db, ctx, "BACKUP_SCHEDULE_UPDATED", "workspace", ctx.workspace_id, before or None,
                     {**after, "next_run_at": _iso(s.next_run_at)}, category="SECURITY")
    return s


# ------------------------------------------------------------------ running a backup
def _actor(ctx_or_none, ws_id: int):
    if ctx_or_none is not None:
        return ctx_or_none
    return SimpleNamespace(workspace_id=ws_id, correlation_id="scheduler", ip=None, user=None)


def _unique(dest: Path, name: str) -> str:
    if not (dest / name).exists():
        return name
    stem = name[:-len(".fmbak")]
    i = 2
    while (dest / f"{stem}-{i}.fmbak").exists():
        i += 1
    return f"{stem}-{i}.fmbak"


def _friendly(e: Exception) -> str:
    if isinstance(e, OSError):
        return f"The backup folder could not be written ({e.strerror or type(e).__name__})."
    if isinstance(e, AppError):
        return e.message
    return f"The backup could not be created ({type(e).__name__})."


def run_backup(app, ws_id: int, trigger: str, ctx=None, now: dt.datetime | None = None) -> BackupRun | None:
    """One scheduled-style backup, end to end. Returns the run (None if another one is running)."""
    if not _run_lock.acquire(blocking=False):
        return None
    try:
        settings = app.state.settings
        factory = app.state.session_factory
        actor = _actor(ctx, ws_id)
        with factory() as db:
            s = get(db, ws_id)
            if s is None or not s.public_key:
                return None
            run = BackupRun(workspace_id=ws_id, trigger=trigger, started_at=now or utcnow(), result="RUNNING",
                            destination=s.destination, key_fingerprint=s.key_fingerprint)
            db.add(run)
            db.commit()
            keypair = {"public_key": s.public_key, "wrapped_private_key": s.wrapped_private_key}
            dest = s.destination
        tmp = None
        try:
            if not dest:
                raise AppError(422, "NO_DESTINATION", "No backup folder is set.")
            check_destination(settings, dest)
            path, name, manifest = bk.create_backup(settings, None, keypair=keypair)
            try:
                folder = Path(dest)
                name = _unique(folder, name)
                tmp = folder / f".{name}.partial"
                shutil.copyfile(path, tmp)
                os.replace(tmp, folder / name)
                tmp = None
                size = (folder / name).stat().st_size
            finally:
                try:
                    path.unlink()
                except OSError:
                    pass
            ok, err = True, None
        except Exception as e:  # reported in the history, the banner and the audit log
            log.warning("scheduled backup failed: %s", e)
            ok, err, name, size, manifest = False, _friendly(e), None, None, None
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        finished = now or utcnow()
        with factory() as db:
            s = get(db, ws_id)
            run = db.get(BackupRun, run.id)
            run.finished_at = finished
            if ok:
                run.result, run.filename, run.size = "SUCCESS", name, size
                s.last_success_at, s.last_error = finished, None
                s.retry_at = s.retry_wait_minutes = None
                audit.record(db, actor, "SCHEDULED_BACKUP_CREATED", "workspace", ws_id, None,
                             {"trigger": trigger, "filename": name, "size": size, "destination": dest,
                              "key_fingerprint": run.key_fingerprint, "counts": manifest["counts"]},
                             category="SECURITY")
                db.flush()
                apply_retention(db, s, actor)
            else:
                run.result, run.error = "FAILED", err
                s.last_failure_at, s.last_error = finished, err
                if trigger == "RETRY" and s.retry_wait_minutes:
                    wait = min(s.retry_wait_minutes * 2, RETRY_MAX_MINUTES)
                else:
                    wait = RETRY_FIRST_MINUTES
                if s.enabled:
                    s.retry_wait_minutes, s.retry_at = wait, finished + dt.timedelta(minutes=wait)
                audit.record(db, actor, "SCHEDULED_BACKUP_FAILED", "workspace", ws_id, None,
                             {"trigger": trigger, "error": err, "destination": dest,
                              "retry_at": _iso(s.retry_at) if s.enabled else None}, category="SECURITY")
            db.commit()
            db.refresh(run)
            db.expunge(run)
            return run
    finally:
        _run_lock.release()


def running() -> bool:
    return _run_lock.locked()


# ------------------------------------------------------------------ retention
def keep_set(runs: list[BackupRun], daily: int, weekly: int, monthly: int) -> set[int]:
    """runs: successful, not yet deleted, newest first. Keeps the newest `daily`, the first backup of each of the
    newest `weekly` weeks and of the newest `monthly` months (server local time). The newest backup always stays."""
    keep: set[int] = set()
    if not runs:
        return keep
    keep.add(runs[0].id)
    keep.update(r.id for r in runs[:daily])
    for count, key in ((weekly, lambda d: tuple(d.isocalendar())[:2]), (monthly, lambda d: (d.year, d.month))):
        if count <= 0:
            continue
        firsts: dict[tuple, BackupRun] = {}
        for r in runs:                       # newest first: the last one seen per period is the earliest
            firsts[key(_to_local(r.started_at))] = r
        for period in sorted(firsts, reverse=True)[:count]:
            keep.add(firsts[period].id)
    return keep


def apply_retention(db, s: BackupSchedule, actor) -> list[str]:
    runs = list(db.scalars(select(BackupRun).where(
        BackupRun.workspace_id == s.workspace_id, BackupRun.result == "SUCCESS", BackupRun.deleted_at.is_(None),
        BackupRun.destination == s.destination, BackupRun.filename.is_not(None))
        .order_by(BackupRun.started_at.desc(), BackupRun.id.desc())))
    keep = keep_set(runs, s.keep_daily if s.frequency == "DAILY" else 0, s.keep_weekly, s.keep_monthly)
    deleted = []
    for r in runs:
        if r.id in keep:
            continue
        if not FILE_RE.match(r.filename or "") or "/" in r.filename or "\\" in r.filename:
            continue   # never anything but a file this application named
        path = Path(s.destination) / r.filename
        try:
            path.unlink()
            reason = "retention"
        except FileNotFoundError:
            reason = "retention (file was already gone)"
        except OSError as e:
            log.warning("could not delete old backup %s: %s", path, e)
            continue
        r.deleted_at, r.deleted_reason = utcnow(), reason
        deleted.append(r.filename)
        audit.record(db, actor, "SCHEDULED_BACKUP_DELETED", "workspace", s.workspace_id, None,
                     {"filename": r.filename, "destination": s.destination, "reason": reason,
                      "backup_started_at": _iso(r.started_at)}, category="SECURITY")
    return deleted


# ------------------------------------------------------------------ the scheduler
def due(s: BackupSchedule, now: dt.datetime) -> str | None:
    if not s.enabled or not s.public_key:
        return None
    if s.next_run_at and s.next_run_at <= now:
        return "MISSED" if now - s.next_run_at > dt.timedelta(minutes=MISSED_AFTER_MINUTES) else "SCHEDULED"
    if s.retry_at and s.retry_at <= now:
        return "RETRY"
    return None


def tick(app, now: dt.datetime | None = None) -> list[BackupRun]:
    """Runs whatever is due. Called every 30 seconds by the scheduler thread (and directly by the tests)."""
    if getattr(app.state, "maintenance", None) or app.state.jobs.running() or running():
        return []
    now = now or utcnow()
    done = []
    with app.state.session_factory() as db:
        schedules = [(s.workspace_id, due(s, now)) for s in db.scalars(select(BackupSchedule))]
        for ws_id, trigger in schedules:
            if trigger in ("SCHEDULED", "MISSED"):
                s = get(db, ws_id)
                s.next_run_at = next_run(s, now)   # the next one is due at its normal time whatever happens now
                s.retry_at = s.retry_wait_minutes = None   # and starts the retry sequence again
                db.commit()
    for ws_id, trigger in schedules:
        if trigger:
            r = run_backup(app, ws_id, trigger, now=now)
            if r is not None:
                done.append(r)
    return done


class Scheduler:
    def __init__(self, app):
        self.app, self.stop_event = app, threading.Event()
        self.thread = threading.Thread(target=self._loop, name="pennywarden-backup-scheduler", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _loop(self) -> None:
        if self.stop_event.wait(FIRST_TICK_SECONDS):
            return
        while not self.stop_event.is_set():
            try:
                tick(self.app)
            except Exception:  # pragma: no cover - never let the scheduler die
                log.exception("backup scheduler")
            from . import updates   # 1.10.0 (#58): the daily update check shares this thread
            updates.tick(self.app)
            self.stop_event.wait(TICK_SECONDS)


def run_now_async(app, ctx) -> None:
    if running() or app.state.jobs.running():
        raise conflict("JOB_RUNNING", "A backup or restore is already running.")
    with app.state.session_factory() as db:
        s = get(db, ctx.workspace_id)
        if s is None or not s.public_key or not s.destination:
            raise validation("Set the folder and the backup passphrase first.", "destination")
    actor = SimpleNamespace(workspace_id=ctx.workspace_id, correlation_id=ctx.correlation_id, ip=ctx.ip,
                            user=SimpleNamespace(id=ctx.user.id, username=ctx.user.username))
    threading.Thread(target=run_backup, args=(app, ctx.workspace_id, "RUN_NOW", actor),
                     name="pennywarden-backup-run-now", daemon=True).start()

