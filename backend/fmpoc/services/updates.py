"""1.10.0 (#58): the update notification.

The backend (never a user's browser) reads the release data file published on pennywarden.org with every release
(scripts/release_data.py, #83) about once a day and keeps the result in the database, so restarts do not fetch again.
The check follows the build's channel (decided 2026-10-09): production builds (built from `main`) read
`releases.json` and see production releases only; test builds (built from `test`) read `releases-test.json` and see
newer test builds and newer production releases; develop and hand-made builds do not check. An Administrator can
turn the check off; then no request is made. Any failure - no internet, the site unreachable, an unexpected answer -
just means no indicator.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import urllib.request

from .. import VERSION, audit
from ..config import build_info
from ..models import UpdateCheck, utcnow

log = logging.getLogger("fmpoc")

INTERVAL = dt.timedelta(hours=24)
RETRY_AFTER_ERROR = dt.timedelta(hours=6)
TIMEOUT = 10
MAX_BYTES = 2_000_000
FILES = {"stable": "releases.json", "test": "releases-test.json"}
_VER = re.compile(r"^\d+\.\d+\.\d+$")


def channel(settings) -> str | None:
    c = (settings.update_channel or "auto").lower()
    if c in ("stable", "test"):
        return c
    if c != "auto":
        return None
    branch = (build_info() or {}).get("branch")
    return {"main": "stable", "test": "test"}.get(branch)


def current(settings) -> dict:
    """The running version; `build` is the test-build number (builds made from `test`), whatever the channel - a test
    build set to production releases only still knows it is build N of its version (2.3.0, #379)."""
    bi = build_info() or {}
    run = bi.get("run")
    branch = bi.get("branch")
    is_test = branch == "test" or (branch != "main" and channel(settings) == "test")
    return {"version": VERSION, "build": int(run) if is_test and str(run).isdigit() else None,
            "branch": bi.get("branch")}


def _vt(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def is_newer(rel: dict, cur: dict, chan: str) -> bool:
    v, mine = _vt(rel["version"]), _vt(cur["version"])
    if v != mine:
        return v > mine
    # 2.3.0 (#379): a test build set to production releases only must still hear about the production release of its
    # own version (on the test channel the newer test builds are what it follows, as before)
    if chan == "stable" and cur.get("build") is not None and rel.get("build") is None:
        return True
    if chan == "test" and rel.get("build") is not None and cur.get("build") is not None:
        return rel["build"] > cur["build"]
    return False


def _clean(rel: dict) -> dict | None:
    """Only the fields the application shows, with types checked (the file comes from outside)."""
    try:
        version = str(rel["version"])
        if not _VER.match(version):
            return None
        build = rel.get("build")
        build = int(build) if build is not None else None
        url = str(rel.get("url") or "")
        if not url.startswith("https://github.com/"):
            url = ""
        return {"version": version, "build": build, "channel": str(rel.get("channel") or ""),
                "date": str(rel.get("date") or "")[:10], "url": url, "notes": str(rel.get("notes") or "")[:20000],
                "tag": str(rel.get("tag") or "")[:40]}
    except (KeyError, TypeError, ValueError):
        return None


def fetch(settings, chan: str) -> list[dict]:
    url = settings.update_base_url.rstrip("/") + "/" + FILES[chan]
    req = urllib.request.Request(url, headers={"User-Agent": f"PennyWarden/{VERSION}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 - fixed https URL from the settings
        raw = r.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("the release data file is too large")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("releases"), list):
        raise ValueError("unexpected release data")
    return [c for c in (_clean(r) for r in data["releases"] if isinstance(r, dict)) if c]


def _row(db) -> UpdateCheck:
    row = db.get(UpdateCheck, 1)
    if row is None:
        row = UpdateCheck(id=1, enabled=True)
        db.add(row)
        db.flush()
    return row


def check(app, force: bool = False, now: dt.datetime | None = None) -> bool:
    """Fetches when due (or forced). Returns True when a request was made."""
    settings = app.state.settings
    if getattr(app.state, "demo", False):     # 2.2.0 (#243): no update check in the demo
        return False
    chan = channel(settings)
    now = now or utcnow()
    with app.state.session_factory() as db:
        row = _row(db)
        if not row.enabled or chan is None:
            db.commit()
            return False
        if not force and row.checked_at and row.channel == chan:
            wait = RETRY_AFTER_ERROR if row.last_error else INTERVAL
            if now - row.checked_at < wait:
                db.commit()
                return False
        cur = current(settings)
        try:
            releases = fetch(settings, chan)
            newer = [r for r in releases if is_newer(r, cur, chan)]
            newer.sort(key=lambda r: (_vt(r["version"]), r["build"] if r["build"] is not None else 10 ** 9), reverse=True)
            row.result_json, row.last_error = json.dumps({"releases": newer}), None
        except Exception as e:  # noqa: BLE001 - offline, blocked, malformed: no indicator, nothing else affected
            log.info("update check: %s", e)
            row.result_json, row.last_error = None, f"{type(e).__name__}: {str(e)[:200]}"
        row.channel, row.checked_at = chan, now
        db.commit()
        return True


def tick(app) -> None:
    try:
        check(app)
    except Exception:  # pragma: no cover - never disturb the scheduler
        log.exception("update check")


def status(db, settings) -> dict:
    row = db.get(UpdateCheck, 1)
    chan = channel(settings)
    enabled = row.enabled if row else True
    cur = current(settings)
    newer: list[dict] = []
    if enabled and chan and row and row.channel == chan and row.result_json:
        try:
            newer = [r for r in json.loads(row.result_json).get("releases", []) if is_newer(r, cur, chan)]
        except (ValueError, TypeError, KeyError):
            newer = []
    latest = newer[0] if newer else None
    download = None
    if latest:
        download = "https://pennywarden.org/#download" if latest["channel"] == "stable" and chan == "stable" \
            else (latest["url"] or None)
    return {"enabled": enabled, "channel": chan, "mode": settings.mode, "current": cur,
            "checked_at": row.checked_at.isoformat() + "Z" if row and row.checked_at else None,
            "error": bool(row and row.last_error), "available": bool(latest),
            "latest": latest, "download_url": download, "releases": newer}


def set_enabled(db, ctx, enabled: bool) -> None:
    row = _row(db)
    if row.enabled == enabled:
        return
    before = row.enabled
    row.enabled, row.updated_at, row.updated_by_user_id = enabled, utcnow(), ctx.user.id
    if not enabled:
        row.result_json = None
    else:
        row.checked_at = None   # check again shortly (the scheduler looks every 30 seconds)
    audit.record(db, ctx, "UPDATE_CHECK_SETTING_CHANGED", "system", None, {"enabled": before}, {"enabled": enabled},
                 category="SECURITY")
