"""2.0.0 (#126): administrative settings - the effective settings view, the server settings editor (config.toml),
renaming the organization and the backup age warning.

The editor only ever writes an explicit allow-list of `[server]` keys in the data folder's config.toml. A setting
that the environment (FM_*) or the command line overrides is locked: an edit to the file would silently do nothing.
The file is rewritten line by line - comments, unknown keys and other sections are kept - then re-parsed and checked
before it atomically replaces the old file, which is kept as config.toml.bak. The running process keeps its settings
until it is restarted ("Restart required" while the file and the running values differ).
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import json
import os
import re
import tempfile
import tomllib
from dataclasses import fields
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import CONFIG_FILE, Settings, _coerce, setting_sources
from ..errors import AppError, Warning_, conflict, require_confirmations, validation
from ..models import AuditEvent, Workspace, utcnow

# ------------------------------------------------------------------ the settings
LABELS = {
    "data_dir": "Data folder", "mode": "Mode", "host": "Bind address", "port": "Port",
    "open_browser": "Open the browser at start (local mode)", "secure_cookies": "Secure cookies",
    "hsts": "HSTS (Strict-Transport-Security)", "trusted_proxies": "Trusted proxies",
    "session_idle_minutes": "Session idle timeout (minutes)", "session_absolute_hours": "Session maximum length (hours)",
    "login_max_failures": "Sign-in brake per address: failed attempts",
    "login_lockout_seconds": "Sign-in brake per address: wait (seconds)",
    "lockout_1_failures": "Account lock 1: failed attempts", "lockout_1_minutes": "Account lock 1: minutes",
    "lockout_2_failures": "Account lock 2: failed attempts", "lockout_2_minutes": "Account lock 2: minutes",
    "lockout_3_failures": "Account lock 3: failed attempts", "lockout_3_minutes": "Account lock 3: minutes",
    "lockout_disable_failures": "Account disabled at failed attempts",
    "restore_max_mb": "Largest backup accepted for a restore (MB)", "backup_folders": "Scheduled backup folders",
    "update_base_url": "Update check address", "update_channel": "Update channel", "log_level": "Log level",
    "debug": "Debug mode", "frontend_dir": "Frontend folder",
    "testing_mode": "Testing mode (test server)",   # 2.2.0 (#231)
}
# The settings an Administrator may change on a server install (#126). Everything else is read-only here.
EDITABLE = ("trusted_proxies", "secure_cookies", "hsts", "session_idle_minutes", "session_absolute_hours",
            "login_max_failures", "login_lockout_seconds", "lockout_1_failures", "lockout_1_minutes",
            "lockout_2_failures", "lockout_2_minutes", "lockout_3_failures", "lockout_3_minutes",
            "lockout_disable_failures", "log_level")
# A wrong value here would lock everyone out: never editable from the application.
READ_ONLY_REASON = {"data_dir": "Changed only by the server owner.", "mode": "Changed only by the server owner.",
                    "host": "Changed only by the server owner.", "port": "Changed only by the server owner.",
                    "testing_mode": "Changed only by the server owner, in config.toml."}
RANGES = {"session_idle_minutes": (5, 480), "session_absolute_hours": (1, 72), "login_max_failures": (3, 50),
          "login_lockout_seconds": (60, 86400), "lockout_1_failures": (3, 50), "lockout_2_failures": (4, 75),
          "lockout_3_failures": (5, 100), "lockout_disable_failures": (6, 200), "lockout_1_minutes": (1, 10080),
          "lockout_2_minutes": (1, 10080), "lockout_3_minutes": (1, 10080)}
CHOICES = {"secure_cookies": ("auto", "true", "false"), "log_level": ("DEBUG", "INFO", "WARNING", "ERROR")}
# Higher is weaker for these; lower is weaker for these (#126: a security-weakening change needs a confirmation)
WEAKER_WHEN_HIGHER = ("session_idle_minutes", "session_absolute_hours", "login_max_failures", "lockout_1_failures",
                      "lockout_2_failures", "lockout_3_failures", "lockout_disable_failures")
WEAKER_WHEN_LOWER = ("login_lockout_seconds", "lockout_1_minutes", "lockout_2_minutes", "lockout_3_minutes")
NOT_SHOWN = ("frontend_dir",)
BACKUP_WARNING_DEFAULT = 7
BACKUP_WARNING_MAX = 365
ORG_NAME_MAX = 120


def _display(name: str, value) -> object:
    if isinstance(value, Path):
        return str(value)
    if name == "backup_folders":
        return [p for p in str(value or "").replace(os.pathsep, "\n").split("\n") if p.strip()]
    return value


def _file_settings(data_dir: Path) -> tuple[dict, dict]:
    """The values the service would start with now (config.toml + environment + the running command line)."""
    raw, sources = setting_sources(data_dir)
    base = Settings(data_dir=data_dir)
    out = {}
    for f in fields(Settings):
        if f.name in raw and f.name != "data_dir":
            try:
                out[f.name] = _coerce(f.name, raw[f.name], getattr(base, f.name))
            except (TypeError, ValueError):
                out[f.name] = getattr(base, f.name)
        else:
            out[f.name] = getattr(base, f.name)
    return out, sources


def effective(settings: Settings, can_edit: bool) -> dict:
    """Every setting with its running value and source; the editor's state on server installs. No secrets: the
    settings hold none (keys and passwords live in the data folder's secrets and the database)."""
    pending, sources = _file_settings(settings.data_dir)
    server = settings.mode == "server"
    rows = []
    for f in fields(Settings):
        n = f.name
        if n in NOT_SHOWN:
            continue
        src = sources.get(n, "default")
        locked = src in ("environment", "command line")
        editable = server and can_edit and n in EDITABLE and not locked
        rows.append({
            "name": n, "label": LABELS.get(n, n), "value": _display(n, getattr(settings, n)), "source": src,
            "editable": editable, "locked": locked and n in EDITABLE,
            "read_only_reason": READ_ONLY_REASON.get(n) if n not in EDITABLE else
            (f"Set by the {src}; change it there." if locked else None),
            "restart_required": n in EDITABLE and pending.get(n) != getattr(settings, n),
            "saved_value": _display(n, pending.get(n)) if n in EDITABLE else None,
            "choices": list(CHOICES[n]) if n in CHOICES else None,
            "range": list(RANGES[n]) if n in RANGES else None,
            "type": "bool" if isinstance(getattr(settings, n), bool) else "int" if isinstance(getattr(settings, n), int)
            else "text",
        })
    return {"mode": settings.mode, "editor": server and can_edit, "config_file": CONFIG_FILE,
            "settings": rows, "restart_required": any(r["restart_required"] for r in rows)}


# ------------------------------------------------------------------ validation
def _validate(name: str, value) -> object:
    if name not in EDITABLE:
        raise validation(f"\"{name}\" can't be changed here.", name)
    label = LABELS[name]
    if name in ("hsts",):
        if not isinstance(value, bool):
            raise validation(f"{label}: on or off.", name)
        return value
    if name in CHOICES:
        v = str(value).strip()
        v = v.upper() if name == "log_level" else v.lower()
        if v not in CHOICES[name]:
            raise validation(f"{label}: one of {', '.join(CHOICES[name])}.", name)
        return v
    if name == "trusted_proxies":
        if not isinstance(value, str) or len(value) > 1000:
            raise validation(f"{label}: a list of addresses separated by commas.", name)
        parts = [p.strip() for p in value.split(",") if p.strip()]
        for p in parts:
            try:
                ipaddress.ip_network(p, strict=False)
            except ValueError:
                raise validation(f"{label}: \"{p[:60]}\" is not an IP address or network.", name) from None
        if len(parts) > 20:
            raise validation(f"{label}: at most 20 entries.", name)
        return ", ".join(parts)
    if name in RANGES:
        if isinstance(value, bool) or not isinstance(value, int):
            raise validation(f"{label}: a whole number.", name)
        lo, hi = RANGES[name]
        if not lo <= value <= hi:
            raise validation(f"{label}: from {lo} to {hi}.", name)
        return value
    raise validation(f"\"{name}\" can't be changed here.", name)  # pragma: no cover


def _check_combination(v: dict) -> None:
    if v["session_idle_minutes"] > v["session_absolute_hours"] * 60:
        raise validation("The idle timeout can't be longer than the maximum session length.", "session_idle_minutes")
    if not v["lockout_1_failures"] < v["lockout_2_failures"] < v["lockout_3_failures"] < v["lockout_disable_failures"]:
        raise validation("The account lock counts must grow: lock 1 < lock 2 < lock 3 < disabled.",
                         "lockout_1_failures")


def _weakening(name: str, old, new, mode: str) -> str | None:
    if old == new:
        return None
    label = LABELS[name]
    if name == "secure_cookies" and new == "false":
        return "Secure cookies off: session cookies are also sent over plain HTTP."
    if name == "secure_cookies" and old == "true" and new == "auto":
        return "Secure cookies set to auto: the Secure flag then depends on how each request arrives."
    if name == "hsts" and old and not new:
        return "HSTS off: browsers no longer insist on HTTPS for this site."
    if name == "log_level" and new == "DEBUG":
        return "Debug logging writes much more detail to the log files."
    if name == "trusted_proxies" and new and not old:
        return "Trusting a proxy lets it set the client address the application sees."
    if name in WEAKER_WHEN_HIGHER and new > old:
        return f"{label}: {old} → {new} is less strict."
    if name in WEAKER_WHEN_LOWER and new < old:
        return f"{label}: {old} → {new} is less strict."
    return None


# ------------------------------------------------------------------ config.toml rewriting
_KEY_RE = re.compile(r"^(\s*)([A-Za-z0-9_-]+)\s*=")
_HEADER_RE = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return json.dumps(str(v), ensure_ascii=False)       # a TOML basic string


def rewrite_toml(text: str, updates: dict) -> str:
    """Sets `updates` in the [server] table, keeping everything else (comments, other keys and tables) as it is.
    A key that is already in [server] has its line replaced; new keys are added at the end of the table (the table
    is created if needed)."""
    lines = text.splitlines()
    out: list[str] = []
    section = None
    done: set[str] = set()
    server_end = None            # index in `out` after the last line of [server]
    for line in lines:
        h = _HEADER_RE.match(line)
        if h:
            if section == "server" and server_end is None:
                server_end = len(out)
            section = h.group(1).strip()
            out.append(line)
            continue
        m = _KEY_RE.match(line)
        if section == "server" and m and m.group(2) in updates:
            out.append(f"{m.group(1)}{m.group(2)} = {_toml_value(updates[m.group(2)])}")
            done.add(m.group(2))
            continue
        out.append(line)
    if section == "server" and server_end is None:
        server_end = len(out)
    rest = [k for k in updates if k not in done]
    if rest:
        add = [f"{k} = {_toml_value(updates[k])}" for k in rest]
        if server_end is None:
            out += (["", "[server]"] if out else ["[server]"]) + add
        else:
            while server_end > 0 and not out[server_end - 1].strip():
                server_end -= 1        # before the blank lines that separate the next table
            out[server_end:server_end] = add
    return "\n".join(out) + "\n"


def write_config(data_dir: Path, updates: dict) -> None:
    """Atomic: write a temporary file next to config.toml, check it parses with the intended values, keep the old
    file as config.toml.bak, then replace."""
    path = data_dir / CONFIG_FILE
    old = path.read_text(encoding="utf-8") if path.is_file() else (
        "# PennyWarden settings (docs/configuration.md). Values here are overridden by FM_* environment variables\n"
        "# and command-line options. Edited by System/About -> Settings; comments and other entries are kept.\n")
    new = rewrite_toml(old, updates)
    try:
        parsed = tomllib.loads(new).get("server", {})
    except tomllib.TOMLDecodeError:
        raise AppError(409, "CONFIG_UNREADABLE", "config.toml could not be read safely; nothing was changed. "
                                                 "Ask the server owner to check the file.") from None
    if any(parsed.get(k) != v for k, v in updates.items()):
        raise AppError(409, "CONFIG_UNREADABLE", "config.toml has an entry this editor can't change safely; nothing "
                                                 "was changed. Ask the server owner to check the file.")
    fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".toml", dir=str(data_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)
            fh.flush()
            os.fsync(fh.fileno())
        if path.is_file():
            try:
                os.chmod(tmp, path.stat().st_mode & 0o777)
            except OSError:  # pragma: no cover - platform dependent
                pass
            bak = data_dir / (CONFIG_FILE + ".bak")
            with open(path, "rb") as src, open(bak, "wb") as dst:
                dst.write(src.read())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(db: Session, ctx, settings: Settings, changes: dict, confirmations: list[str] | None,
         password_check) -> dict:
    """Validates every change (allow-list, ranges, combinations), asks for the password when trusted proxies change
    and for a confirmation when a change weakens security, writes config.toml and audits before and after."""
    if settings.mode != "server":
        raise conflict("SERVER_ONLY", "Settings are edited in config.toml on a local install.")
    if not changes:
        raise validation("Nothing to change.")
    current, sources = _file_settings(settings.data_dir)
    clean = {}
    for name, value in changes.items():
        if name not in EDITABLE:
            raise validation(f"\"{str(name)[:40]}\" can't be changed here.", str(name)[:40])
        if sources.get(name) in ("environment", "command line"):
            raise conflict("SETTING_LOCKED", f"{LABELS[name]} is set by the {sources[name]}; change it there.")
        clean[name] = _validate(name, value)
    changed = {k: v for k, v in clean.items() if current.get(k) != v}
    if not changed:
        return {"changed": []}
    _check_combination({**{k: current[k] for k in EDITABLE}, **changed})
    if "trusted_proxies" in changed:
        password_check()
    warnings = [Warning_("SECURITY_WEAKENING", msg, setting=k)
                for k, v in changed.items() if (msg := _weakening(k, current.get(k), v, settings.mode))]
    if warnings:
        msgs = " ".join(w.message for w in warnings)
        require_confirmations([Warning_("SECURITY_WEAKENING", f"These changes make the server less strict: {msgs}")],
                              confirmations)
    write_config(settings.data_dir, changed)
    audit.record(db, ctx, "SERVER_SETTINGS_CHANGED", "workspace", ctx.workspace_id,
                 {k: current.get(k) for k in changed}, dict(changed), category="SECURITY")
    return {"changed": sorted(changed)}


# ------------------------------------------------------------------ organization name
def rename_organization(db: Session, ctx, name: str) -> Workspace:
    name = (name or "").strip()
    if not name or len(name) > ORG_NAME_MAX:
        raise validation(f"The organization name is required (at most {ORG_NAME_MAX} characters).", "name")
    if any(ord(c) < 32 for c in name):
        raise validation("The organization name can't contain control characters.", "name")
    ws = db.get(Workspace, ctx.workspace_id)
    if ws.name == name:
        return ws
    before = ws.name
    ws.name = name
    from . import organization            # 2.1.0 (#314): the organization entity carries the name too
    organization.sync_name(db, ws)
    db.flush()
    audit.record(db, ctx, "ORGANIZATION_RENAMED", "workspace", ws.id, {"name": before}, {"name": name})
    return ws


# ------------------------------------------------------------------ backup age warning
BACKUP_EVENTS = ("BACKUP_CREATED", "SCHEDULED_BACKUP_CREATED")
RESTORE_EVENTS = ("SYSTEM_RESTORED",)


def last_backup_at(db: Session, ws_id: int) -> dt.datetime | None:
    from . import testing     # 2.2.0 (#231): a testing-mode Administrator may set it
    override = testing.last_backup_override(db, ws_id)
    if override is not None:
        return override
    return db.scalar(select(func.max(AuditEvent.timestamp)).where(
        AuditEvent.workspace_id == ws_id, AuditEvent.action.in_(BACKUP_EVENTS)))


def backup_age(db: Session, ws_id: int, now: dt.datetime | None = None) -> dict:
    """The warning shown to Administrators when no backup has been made for `backup_warning_days` days. The clock
    starts at the last backup, else the last restore or the initialization - a new or restored installation gets the
    same grace period before the first warning."""
    ws = db.get(Workspace, ws_id)
    days = ws.backup_warning_days if ws and ws.backup_warning_days is not None else BACKUP_WARNING_DEFAULT
    last = last_backup_at(db, ws_id)
    restored = db.scalar(select(func.max(AuditEvent.timestamp)).where(
        AuditEvent.workspace_id == ws_id, AuditEvent.action.in_(RESTORE_EVENTS)))
    start = max(x for x in (last, restored, ws.bootstrap_completed_at if ws else None, ws.created_at if ws else None)
                if x is not None) if ws else None
    from . import testing     # 2.2.0 (#231): the time a testing-mode Administrator set is the only clock
    if ws and testing.last_backup_override(db, ws_id) is not None:
        start = last
    now = now or utcnow()
    stale = bool(days and start and now - start > dt.timedelta(days=days))
    out = {"warning_days": days, "last_backup_at": last.isoformat() + "Z" if last else None, "stale": stale}
    if stale:
        age = (now - start).days
        out["message"] = (f"No backup has been made for {age} days." if last else
                          f"No backup has been made on this installation yet ({age} days).") + \
            " Create a backup now and keep it off this machine."
    return out


def set_backup_warning_days(db: Session, ctx, days: int) -> int:
    if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= BACKUP_WARNING_MAX:
        raise validation(f"Days without a backup before the warning: 0 (off) to {BACKUP_WARNING_MAX}.", "days")
    ws = db.get(Workspace, ctx.workspace_id)
    before = ws.backup_warning_days
    if before != days:
        ws.backup_warning_days = days
        db.flush()
        audit.record(db, ctx, "BACKUP_WARNING_CHANGED", "workspace", ws.id, {"days": before}, {"days": days})
    return days
