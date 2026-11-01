"""2.0.0 (#131): the Administrator's security overview - read-only, counts and settings only (no secrets, session
identifiers or financial content). Each item says whether it needs attention and what to do.

Needs attention (decided 2026-10-12): plain HTTP on a network install, users without two-step verification, the last
backup older than the backup reminder's days, locked accounts. Informational: the number of Administrators, HSTS,
secure cookies, trusted proxies, disabled accounts."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import is_loopback
from ..models import User, UserMfa, utcnow
from ..permissions import ADMINISTRATOR, ROLE_DEFS
from . import admin_settings, recovery

ROLE_NAMES = {c: n for c, n, _d in ROLE_DEFS}


def _item(key, title, value, attention, note):
    return {"key": key, "title": title, "value": value, "status": "attention" if attention else "ok" if attention is False
            else "info", "note": note}


def overview(db: Session, settings, ws_id: int, request_https: bool) -> dict:
    users = list(db.scalars(select(User).where(User.workspace_id == ws_id)))
    active = [u for u in users if u.active]
    mfa_on = set(db.scalars(select(UserMfa.user_id).where(UserMfa.enabled_at.is_not(None))))
    without = [u for u in active if u.id not in mfa_on]
    by_role: dict[str, int] = {}
    for u in without:
        for r in u.role_codes or {"(no role)"}:
            by_role[ROLE_NAMES.get(r, r)] = by_role.get(ROLE_NAMES.get(r, r), 0) + 1
    admins = [u for u in active if ADMINISTRATOR in u.role_codes]
    locked = [u for u in active if recovery.is_locked(u)]
    disabled = [u for u in users if not u.active]
    network = settings.mode == "server" and not is_loopback(settings.host)
    plain_http = settings.mode == "server" and not request_https
    age = admin_settings.backup_age(db, ws_id, utcnow())
    items = [
        _item("https", "HTTPS", "Yes" if request_https else "No (plain HTTP)",
              True if (plain_http and (network or settings.trusted_proxies)) else (False if request_https else None),
              "Browsers reach PennyWarden over HTTPS." if request_https else
              ("This page was opened over plain HTTP. On a network, put an HTTPS front end (Caddy, a Cloudflare Tunnel) "
               "in front of PennyWarden." if settings.mode == "server" else
               "A local install is only reachable from this computer, so HTTPS isn't needed.")),
        _item("two_step", "Two-step verification",
              f"{len(active) - len(without)} of {len(active)} active users", bool(without) if active else False,
              "Every active user has it." if not without else
              "Without it: " + ", ".join(f"{n} {r}" for r, n in sorted(by_role.items())) + ". " +
              ("On a server they set it up at their next sign-in." if settings.mode == "server" else
               "Each user can turn it on under My account.")),
        _item("backup", "Last backup", age["last_backup_at"] or "None yet", bool(age["stale"]) if age["warning_days"] else None,
              age.get("message") or ("Backups are recent." if age["last_backup_at"] else "Make a backup under Backup / Restore.")),
        _item("locked", "Locked accounts", str(len(locked)), bool(locked),
              "None." if not locked else "Locked after failed sign-in attempts: " + ", ".join(u.username for u in locked) +
              ". Check with the person, then re-enable or reset the password under Users."),
        _item("admins", "Administrators", str(len(admins)), None,
              "Keep at least two so one can help the other, and no more than needed."),
        _item("secure_cookies", "Secure cookies", settings.secure_cookies, None,
              "\"true\" behind HTTPS; \"auto\" follows each request; \"false\" only for testing."),
        _item("hsts", "HSTS", "On" if settings.hsts else "Off", None,
              "Turn it on once the site is always reached over HTTPS."),
        _item("trusted_proxies", "Trusted proxies", settings.trusted_proxies or "None", None,
              "Set it to the address of the HTTPS front end (usually 127.0.0.1) so the real client addresses are seen."),
        _item("disabled", "Disabled accounts", str(len(disabled)), None,
              "Disabled accounts can't sign in; their history is kept."),
    ]
    # 2.4.0 (#251): separation of duties - informational, never a warning or a block
    whole = [u for u in active if {"BUDGET_MANAGER", "INVOICE_MANAGER", "REGISTER_USER"} <= set(u.role_codes)]
    items.append(_item("whole_cycle", "Whole invoice cycle in one account", str(len(whole)), None,
                       "No one holds Budget Manager, Invoice Manager and Register User together." if not whole else
                       "Budget Manager + Invoice Manager + Register User: " + ", ".join(u.username for u in whole)
                       + ". This is allowed (a small organization may need it); with more people, splitting these "
                       "roles lets someone else check each step."))
    return {"mode": settings.mode, "items": items, "attention": sum(1 for i in items if i["status"] == "attention")}
