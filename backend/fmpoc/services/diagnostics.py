"""2.0.0 (#128): the sanitized diagnostics download, and the storage facts it shares with the health check (#129).

The file is built on demand from facts about the installation only: version and build, mode, operating system,
the effective settings (paths shortened, no secrets - the settings hold none), database and attachment sizes, free
disk space, the migration state, counts of users and sessions, and the last 1,000 log lines after scrubbing. It never
reads financial tables (BR-003), the encryption key, password or token columns."""
from __future__ import annotations

import datetime as dt
import json
import os
import platform
import re
import shutil
import sys
from collections import deque
from pathlib import Path

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import VERSION, audit
from ..config import build_info
from ..db import alembic_config
from ..models import AuthSession, User, Workspace, utcnow
from . import admin_settings

LOG_LINES = 1000
LOG_FILE = "fmpoc.log"


# ------------------------------------------------------------------ facts shared with the health check
def dir_size(path: Path) -> tuple[int, int]:
    """(bytes, files) under a folder; unreadable entries are skipped."""
    total = files = 0
    if not path.is_dir():
        return 0, 0
    for root, _dirs, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(root, n))
                files += 1
            except OSError:
                continue
    return total, files


def database_size(settings) -> int:
    size = 0
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(settings.database_path) + suffix)
        try:
            size += p.stat().st_size
        except OSError:
            pass
    return size


def disk(settings) -> dict:
    try:
        u = shutil.disk_usage(settings.data_dir)
        return {"total": u.total, "free": u.free, "free_percent": round(u.free * 100 / u.total, 1) if u.total else None}
    except OSError:
        return {"total": None, "free": None, "free_percent": None}


def migration_state(db: Session, settings) -> dict:
    head = ScriptDirectory.from_config(alembic_config(settings.database_url)).get_current_head()
    current = MigrationContext.configure(db.connection()).get_current_revision()
    return {"current": current, "head": head, "up_to_date": current == head}


def storage(db: Session, settings) -> dict:
    att, att_files = dir_size(settings.attachments_dir)
    return {"database_bytes": database_size(settings), "attachments_bytes": att, "attachment_files": att_files,
            **shared_attachment_files(db), "disk": disk(settings), "migrations": migration_state(db, settings)}


def shared_attachment_files(db: Session) -> dict:
    """2.4.0 (#425): counts only - how many attachment records exist, how many stored files more than one of them
    shares, and the space deduplication saved (no file names or owners)."""
    from sqlalchemy import func, select

    from ..models import Attachment
    per_file = (select(Attachment.storage_key, func.count(Attachment.id).label("n"),
                       func.max(Attachment.size_bytes).label("size")).group_by(Attachment.storage_key).subquery())
    records, shared, saved = db.execute(select(
        func.coalesce(func.sum(per_file.c.n), 0),
        func.coalesce(func.sum(case_when(per_file.c.n > 1, 1)), 0),
        func.coalesce(func.sum((per_file.c.n - 1) * per_file.c.size), 0))).one()
    return {"attachment_records": int(records), "attachment_shared_files": int(shared),
            "attachment_bytes_saved": int(saved)}


def case_when(cond, value):
    from sqlalchemy import case
    return case((cond, value), else_=0)


# ------------------------------------------------------------------ scrubbing
_SCRUB = [
    # key=value pairs that may carry a secret
    (re.compile(r"(?i)\b(password|passwd|passphrase|secret|token|cookie|csrf|session|authorization|api[_-]?key|"
                r"account_number|enc_key|fp_key|key)\b([\"']?\s*[:=]\s*)([^\s,;&\"']+)"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    # long token-like strings (session tokens, keys, hashes)
    (re.compile(r"\b[A-Za-z0-9_-]{24,}={0,2}"), "[REDACTED]"),
    # money amounts and long digit runs (account and routing numbers)
    (re.compile(r"[$€£]\s?-?\d[\d,]*(\.\d+)?"), "[AMOUNT]"),
    (re.compile(r"(?<![\d:.,])-?\d{1,3}(,\d{3})+(\.\d{1,2})?(?![\d.,])|(?<![\d.])-?\d+\.\d{2}(?![\d.])"), "[AMOUNT]"),
    (re.compile(r"\b\d{6,}\b"), "[NUMBER]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
]


def scrub(line: str) -> str:
    for rx, rep in _SCRUB:
        line = rx.sub(rep, line)
    return line


def _home(text: str) -> str:
    home = str(Path.home())
    return text.replace(home, "~") if home and home not in ("/", "") else text


def recent_log_lines(settings, n: int = LOG_LINES) -> list[str]:
    """The last `n` lines of the log (the rotated files first when the current one is shorter), scrubbed."""
    files = [settings.logs_dir / f"{LOG_FILE}.{i}" for i in range(5, 0, -1)] + [settings.logs_dir / LOG_FILE]
    tail: deque[str] = deque(maxlen=n)
    for f in files:
        try:
            with f.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    tail.append(line.rstrip("\n")[:2000])
        except OSError:
            continue
    return [_home(scrub(x)) for x in tail]


# ------------------------------------------------------------------ the file
def _settings_rows(settings) -> list[dict]:
    rows = []
    for r in admin_settings.effective(settings, False)["settings"]:
        v = r["value"]
        v = [_home(str(x)) for x in v] if isinstance(v, list) else _home(v) if isinstance(v, str) else v
        rows.append({"name": r["name"], "value": v, "source": r["source"]})
    return rows


def build(db: Session, settings, ctx) -> tuple[bytes, str]:
    now = utcnow()
    idle = dt.timedelta(minutes=settings.session_idle_minutes)
    ws = db.get(Workspace, ctx.workspace_id)
    users = db.scalar(select(func.count(User.id)).where(User.workspace_id == ctx.workspace_id)) or 0
    active_users = db.scalar(select(func.count(User.id)).where(User.workspace_id == ctx.workspace_id,
                                                                User.active.is_(True))) or 0
    sessions = db.scalar(select(func.count(AuthSession.id)).join(User, User.id == AuthSession.user_id).where(
        User.workspace_id == ctx.workspace_id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > now,
        AuthSession.last_seen_at > now - idle)) or 0
    data = {
        "kind": "PennyWarden diagnostics",
        "generated_at": now.replace(microsecond=0).isoformat() + "Z",
        "version": VERSION, "build": build_info(), "mode": settings.mode,
        "system": {"os": platform.platform(terse=True), "machine": platform.machine(),
                   "python": sys.version.split()[0], "frozen": bool(getattr(sys, "frozen", False))},
        "settings": _settings_rows(settings),
        "storage": storage(db, settings),
        "counts": {"users": users, "active_users": active_users, "active_sessions": sessions},
        "modules": {"fundraisers": bool(ws.fundraisers_enabled), "payments": bool(ws.checks_enabled),
                    "donations": bool(ws.donations_enabled), "invoices": bool(ws.invoices_enabled)} if ws else {},
        "log": {"file": LOG_FILE, "lines": recent_log_lines(settings),
                "note": "Scrubbed: secrets, long tokens, amounts, long numbers and email addresses are replaced."},
    }
    body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    name = f"pennywarden-diagnostics-{now:%Y%m%d-%H%M%S}.json"
    audit.record(db, ctx, "DIAGNOSTICS_DOWNLOADED", "workspace", ctx.workspace_id, None,
                 {"bytes": len(body), "log_lines": len(data["log"]["lines"])}, category="SECURITY")
    return body, name


# ------------------------------------------------------------------ health check (#129)
LOW_DISK_BYTES = 1024 ** 3          # 1 GB
LOW_DISK_PERCENT = 10.0


def low_disk(d: dict) -> bool:
    """Free space on the data folder's volume below 1 GB or 10 %, whichever comes first (decided 2026-10-12)."""
    if d.get("free") is None:
        return False
    return d["free"] < LOW_DISK_BYTES or (d.get("free_percent") is not None and d["free_percent"] < LOW_DISK_PERCENT)


def health(db: Session, settings) -> dict:
    st = storage(db, settings)
    out = {**st, "low_disk": low_disk(st["disk"]),
           "thresholds": {"free_bytes": LOW_DISK_BYTES, "free_percent": LOW_DISK_PERCENT}}
    if out["low_disk"]:
        out["low_disk_message"] = (f"Low disk space: {st['disk']['free'] / 1024 ** 3:.1f} GB "
                                   f"({st['disk']['free_percent']} %) free where PennyWarden keeps its data. "
                                   "Free some space or move the data to a larger disk.")
    return out


def integrity_check(db: Session, ctx) -> dict:
    """SQLite's integrity check through the application (BR-084). It reads the whole database inside one read
    transaction, so it is safe while people are working (it does not block them in WAL mode). The result is OK or a
    plain failure message: no SQL, paths or page numbers are returned (BR-104); the details go to the log."""
    import logging
    started = utcnow()
    try:
        rows = [r[0] for r in db.connection().exec_driver_sql("PRAGMA integrity_check(20)").fetchall()]
        ok = rows == ["ok"]
        if not ok:
            logging.getLogger("fmpoc").error("integrity check found %d problem(s): %s", len(rows), "; ".join(rows)[:2000])
    except Exception as e:  # noqa: BLE001 - a damaged file can fail in many ways
        logging.getLogger("fmpoc").error("integrity check could not run: %s", type(e).__name__)
        db.rollback()
        ok, rows = False, ["error"]
    seconds = round((utcnow() - started).total_seconds(), 2)
    audit.record(db, ctx, "HEALTH_CHECK_RUN", "workspace", ctx.workspace_id, None,
                 {"result": "OK" if ok else "FAILED", "seconds": seconds}, category="SECURITY")
    return {"ok": ok, "checked_at": started.replace(microsecond=0).isoformat() + "Z", "seconds": seconds,
            "message": "The database passed the integrity check." if ok else
            "The database integrity check found a problem. Do not restore over your backups: make a copy of the data "
            "folder, then restore the most recent good backup or ask for help (the details are in the log)."}
