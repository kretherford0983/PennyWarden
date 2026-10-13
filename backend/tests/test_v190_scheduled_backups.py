"""1.9.0 (#62): scheduled automatic backups - settings, destination rules (server list / local any folder), key-pair
encryption (the application cannot open its own backups; the passphrase restores them through the normal Restore),
schedule and missed runs, retries 1-2-4...24 h, retention (only files the app wrote), banner, Run now, Test, audit,
access."""
import datetime as dt
import os
import tempfile
import time
from pathlib import Path

import pytest

from conftest import PASSWORD, Api
from test_v141_backup import _restore

from fmpoc.app import create_app
from fmpoc.config import load_settings
from fmpoc.models import BackupRun, BackupSchedule
from fmpoc.services import backup as bk
from fmpoc.services import scheduled_backup as sb

PP = "scheduled backups passphrase 7"


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "nas-share"
    d.mkdir()
    return d


def _save(env, folder, **kw):
    body = {"enabled": True, "frequency": "DAILY", "time_of_day": "02:00", "destination": str(folder),
            "keep_daily": 3, "keep_weekly": 2, "keep_monthly": 2, "passphrase": PP, "passphrase_confirmation": PP,
            "password": PASSWORD, **kw}
    return env.admin.put("/api/system/backup-schedule", body)


def _sched(app):
    with app.state.session_factory() as db:
        s = db.query(BackupSchedule).one()
        db.expunge(s)
        return s


def _set(app, **values):
    with app.state.session_factory() as db:
        s = db.query(BackupSchedule).one()
        for k, v in values.items():
            setattr(s, k, v)
        db.commit()


def _files(folder):
    return sorted(p.name for p in Path(folder).iterdir() if p.suffix == ".fmbak")


def test_settings_validation_and_next_run(env, folder):
    a = env.admin
    assert a.get("/api/system/backup-schedule").json()["passphrase_set"] is False
    assert _save(env, folder, passphrase=None, passphrase_confirmation=None).status_code == 422   # needs a passphrase
    assert _save(env, folder, passphrase="short", passphrase_confirmation="short").status_code == 422
    assert _save(env, folder, passphrase_confirmation=PP + "x").status_code == 422
    r = _save(env, folder, password="wrong-password-1")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INCORRECT_PASSWORD"
    assert _save(env, folder, time_of_day="25:00").status_code == 422
    assert _save(env, folder, destination="relative/folder").status_code == 422
    assert _save(env, folder, destination=str(folder / "missing")).status_code == 422
    assert _save(env, folder, keep_daily=0, keep_weekly=0, keep_monthly=0).status_code == 422
    r = _save(env, folder)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["enabled"] and j["passphrase_set"] and j["next_run_local"].endswith("02:00") and j["key_fingerprint"]
    s = _sched(env.app)
    assert s.public_key and s.wrapped_private_key and PP not in s.wrapped_private_key
    # a weekly schedule offers no daily count; it lands on the chosen day
    r = env.admin.put("/api/system/backup-schedule", {"enabled": True, "frequency": "WEEKLY", "weekday": 6,
                                                      "time_of_day": "23:30", "destination": str(folder),
                                                      "keep_daily": 5, "keep_weekly": 4, "keep_monthly": 3})
    assert r.status_code == 200 and r.json()["keep_daily"] == 0
    assert dt.datetime.fromisoformat(r.json()["next_run_at"][:-1]).replace(tzinfo=dt.timezone.utc).astimezone().weekday() == 6
    ev = env.admin.get("/api/audit-events?action=BACKUP_SCHEDULE_UPDATED").json()["items"]
    assert ev and PP not in str(ev)
    assert env.admin.get("/api/audit-events?action=BACKUP_PASSPHRASE_SET").json()["total"] == 1


def test_scheduled_backup_restores_with_the_passphrase_only(env, base, folder):
    assert _save(env, folder).status_code == 200
    _set(env.app, next_run_at=dt.datetime.utcnow() - dt.timedelta(minutes=1))
    runs = sb.tick(env.app)
    assert len(runs) == 1 and runs[0].result == "SUCCESS" and runs[0].trigger == "SCHEDULED"
    files = _files(folder)
    assert files == [runs[0].filename] and files[0].startswith("pennywarden-backup-acme-org-")
    data = (folder / files[0]).read_bytes()
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(bk.BackupError):
            bk.decrypt_file(folder / files[0], "wrong passphrase 123", Path(td) / "x")
    # the next one is tomorrow at 02:00
    assert _sched(env.app).next_run_at > dt.datetime.utcnow()
    # restore through the normal Restore screen (same passphrase), and a wrong one is refused
    j = _restore(env.admin, data, passphrase="wrong passphrase 123", password=PASSWORD, confirm="RESTORE")
    assert j["state"] == "failed" and "passphrase" in j["error"].lower()
    j = _restore(env.admin, data, passphrase=PP, password=PASSWORD, confirm="RESTORE")
    assert j["state"] == "done", j


def test_passphrase_change_keeps_old_backups_on_the_old_passphrase(env, folder):
    _save(env, folder)
    old = sb.run_backup(env.app, 1, "RUN_NOW")
    r = _save(env, folder, passphrase="a completely new phrase 9", passphrase_confirmation="a completely new phrase 9")
    assert r.status_code == 200
    new = sb.run_backup(env.app, 1, "RUN_NOW")
    with tempfile.TemporaryDirectory() as td:
        bk.decrypt_file(folder / old.filename, PP, Path(td) / "a")
        bk.decrypt_file(folder / new.filename, "a completely new phrase 9", Path(td) / "b")
        with pytest.raises(bk.BackupError):
            bk.decrypt_file(folder / old.filename, "a completely new phrase 9", Path(td) / "c")
    assert old.key_fingerprint != new.key_fingerprint


def test_server_mode_only_listed_folders(tmp_path, folder):
    other = tmp_path / "other"
    other.mkdir()
    app = create_app(load_settings({"data_dir": str(tmp_path / "srv"), "mode": "server", "login_max_failures": 1000,
                                    "backup_folders": [str(folder)]}))
    from types import SimpleNamespace
    from fmpoc.errors import AppError
    assert sb.check_destination(app.state.settings, str(folder)) == str(folder)
    with pytest.raises(AppError):
        sb.check_destination(app.state.settings, str(other))
    s2 = load_settings({"data_dir": str(tmp_path / "srv2"), "mode": "server"})
    with pytest.raises(AppError):
        sb.check_destination(s2, str(folder))                   # nothing configured: nothing allowed
    os.environ["FM_BACKUP_FOLDERS"] = os.pathsep.join([str(folder), str(other)])
    try:
        s3 = load_settings({"data_dir": str(tmp_path / "srv3"), "mode": "server"})
        assert sb.check_destination(s3, str(other)) == str(other)
    finally:
        del os.environ["FM_BACKUP_FOLDERS"]
    assert SimpleNamespace


def test_local_any_writable_folder_and_test_button(env, folder):
    r = env.admin.post("/api/system/backup-schedule/test", {"destination": str(folder)})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert list(folder.iterdir()) == []                          # no test file left behind
    assert env.admin.post("/api/system/backup-schedule/test", {"destination": str(folder / "nope")}).status_code == 422


def test_failure_retries_with_doubling_waits_and_banner(env, folder):
    _save(env, folder)
    folder.rmdir()                                               # the NAS share is gone
    t0 = dt.datetime.utcnow()
    _set(env.app, next_run_at=t0 - dt.timedelta(minutes=1))
    r = sb.tick(env.app, now=t0)[0]
    assert r.result == "FAILED" and "folder" in r.error.lower()
    s = _sched(env.app)
    assert s.retry_wait_minutes == 60 and s.retry_at == t0 + dt.timedelta(minutes=60)
    banner = env.admin.get("/api/system/backup-schedule/alert").json()
    assert banner["failed"] is True and "failed" in banner["message"]
    assert env.bm.get("/api/system/backup-schedule/alert").status_code == 403
    _set(env.app, next_run_at=t0 + dt.timedelta(days=30))     # keep the next scheduled run out of the way
    waits = []
    now = t0
    for _ in range(7):
        now = _sched(env.app).retry_at
        assert sb.tick(env.app, now=now - dt.timedelta(seconds=1)) == []     # not yet
        r = sb.tick(env.app, now=now)[0]
        assert r.trigger == "RETRY"
        waits.append(_sched(env.app).retry_wait_minutes)
    assert waits == [120, 240, 480, 960, 1440, 1440, 1440]
    # the next scheduled backup runs at its time regardless and succeeds -> banner gone, retries reset
    folder.mkdir()
    _set(env.app, next_run_at=now + dt.timedelta(minutes=5))
    r = sb.tick(env.app, now=now + dt.timedelta(minutes=5))[0]
    assert r.trigger == "SCHEDULED" and r.result == "SUCCESS"
    s = _sched(env.app)
    assert s.retry_at is None and s.retry_wait_minutes is None
    assert env.admin.get("/api/system/backup-schedule/alert").json()["failed"] is False   # 2.0.0 adds other banners
    acts = {e["action"] for e in env.admin.get("/api/audit-events?page_size=200").json()["items"]}
    assert {"SCHEDULED_BACKUP_FAILED", "SCHEDULED_BACKUP_CREATED"} <= acts


def test_missed_backup_runs_at_the_next_start(env, folder):
    _save(env, folder)
    _set(env.app, next_run_at=dt.datetime.utcnow() - dt.timedelta(hours=7))   # the app was off at 02:00
    r = sb.tick(env.app)[0]
    assert r.trigger == "MISSED" and r.result == "SUCCESS"
    assert sb.tick(env.app) == []                                # once, then the normal schedule


def test_retention_keeps_daily_weekly_monthly_and_never_other_files(env, folder):
    _save(env, folder)
    (folder / "family-photos.zip").write_bytes(b"not ours")
    (folder / "pennywarden-backup-acme-org-20200101-000000.fmbak").write_bytes(b"made by hand, not in the history")
    start = dt.datetime(2026, 1, 1, 12, 0)                       # 120 days of daily backups
    for i in range(120):
        sb.run_backup(env.app, 1, "SCHEDULED", now=start + dt.timedelta(days=i))
    with env.app.state.session_factory() as db:
        kept = [r for r in db.query(BackupRun).filter(BackupRun.result == "SUCCESS", BackupRun.deleted_at.is_(None))
                .order_by(BackupRun.started_at.desc())]
        runs_all = db.query(BackupRun).count()
    assert runs_all == 120
    days = [sb._to_local(r.started_at).date() for r in kept]
    last = sb._to_local(start + dt.timedelta(days=119)).date()
    assert last == dt.date(2026, 4, 30)                                   # a Thursday
    # 3 daily (Apr 30, 29, 28); weekly: the first backup of the 2 newest weeks (Mon Apr 27, Mon Apr 20);
    # monthly: the first of the 2 newest months (Apr 1, Mar 1)
    assert days == [dt.date(2026, 4, d) for d in (30, 29, 28, 27, 20, 1)] + [dt.date(2026, 3, 1)]
    on_disk = set(_files(folder))
    assert {r.filename for r in kept} | {"pennywarden-backup-acme-org-20200101-000000.fmbak"} == on_disk
    assert (folder / "family-photos.zip").exists()
    dels = env.admin.get("/api/audit-events?action=SCHEDULED_BACKUP_DELETED&page_size=200").json()["total"]
    assert dels == 120 - len(kept)


def test_keep_set_rules():
    class R:
        def __init__(self, i, d):
            self.id, self.started_at = i, d
    base = dt.datetime(2026, 3, 31, 12)
    runs = [R(i, base - dt.timedelta(days=i)) for i in range(60)]          # newest first
    keep = sb.keep_set(runs, 3, 2, 2)
    assert {0, 1, 2} <= keep
    assert sb.keep_set(runs, 0, 0, 1) >= {0}                                   # the newest always stays


def test_run_now_writes_and_shows_in_history(env, folder):
    assert env.admin.post("/api/system/backup-schedule/run").status_code == 422             # not set up yet
    _save(env, folder, enabled=False)
    r = env.admin.post("/api/system/backup-schedule/run")
    assert r.status_code == 202
    end = time.time() + 60
    while time.time() < end:
        h = env.admin.get("/api/system/backup-schedule").json()["history"]
        if h and h[0]["result"] != "RUNNING":
            break
        time.sleep(0.1)
    assert h[0]["trigger"] == "RUN_NOW" and h[0]["result"] == "SUCCESS" and h[0]["size"] > 0
    assert _files(folder) == [h[0]["filename"]]


def test_disabled_schedule_does_not_run(env, folder):
    _save(env, folder, enabled=False)
    assert sb.tick(env.app, now=dt.datetime.utcnow() + dt.timedelta(days=3)) == []


def test_only_administrators(env, folder):
    for c in (env.bm, env.bu, env.ru, env.auditor):
        assert c.get("/api/system/backup-schedule").status_code == 403
        assert c.put("/api/system/backup-schedule", {"enabled": False}).status_code == 403
        assert c.post("/api/system/backup-schedule/run").status_code == 403
        assert c.post("/api/system/backup-schedule/test", {"destination": str(folder)}).status_code == 403
    assert Api(env.app).get("/api/system/backup-schedule").status_code == 401
