"""2.2.0 (#231): testing mode - config.toml only, server installs only; a banner flag; an Administrator's Testing tab
that moves timers and schedules (no global fake clock, no hard deletes); every action recorded as TESTING_* in the
Security category; testing-mode backups are marked and refused by the app on a server not in testing mode."""
from __future__ import annotations

import datetime as dt

import pytest

from conftest import PASSWORD, Api, initialize
from test_v141_backup import PASS, _backup, _restore, _wait
from test_v141_mfa import _enroll

from fmpoc.app import create_app
from fmpoc.config import load_settings
from fmpoc.services import testing


@pytest.fixture
def test_server(tmp_path):
    app = create_app(load_settings({"data_dir": str(tmp_path / "test-server"), "mode": "server",
                                    "testing_mode": True, "login_max_failures": 50}))
    a = initialize(app)
    a.csrf = a.get("/api/auth/me").json()["csrf_token"]
    _enroll(a)
    yield app, a
    testing.ENABLED = False


def _events(a, action):
    return a.get(f"/api/audit-events?action={action}").json()["items"]


def test_off_by_default_and_local_installs_ignore_it(env, tmp_path):
    assert env.admin.get("/api/system/status").json()["testing_mode"] is False
    assert env.admin.get("/api/system/testing").status_code == 404
    assert env.admin.post("/api/system/testing/update-check").status_code == 404
    local = create_app(load_settings({"data_dir": str(tmp_path / "local"), "testing_mode": True}))
    assert local.state.testing_mode is False and testing.ENABLED is False
    # read-only in the settings view, never editable
    rows = {r["name"]: r for r in env.admin.get("/api/system/settings").json()["settings"]}
    assert rows["testing_mode"]["value"] is False and rows["testing_mode"]["editable"] is False


def test_banner_flag_and_admin_only(test_server):
    app, a = test_server
    assert Api(app).get("/api/system/status").json()["testing_mode"] is True      # on the sign-in page too
    v = a.get("/api/system/testing")
    assert v.status_code == 200 and v.json()["testing_mode"] is True
    rows = {r["name"]: r for r in a.get("/api/system/settings").json()["settings"]}
    assert rows["testing_mode"]["value"] is True and rows["testing_mode"]["editable"] is False
    # the settings editor can't turn it off (or on) either
    r = a.put("/api/system/settings", {"changes": {"testing_mode": False}, "confirmations": [], "password": PASSWORD})
    assert r.status_code == 422


def test_schedule_retry_backdate_and_last_backup(test_server, tmp_path):
    app, a = test_server
    folder = tmp_path / "backups"
    folder.mkdir()
    s = app.state.settings
    object.__setattr__(s, "backup_folders", str(folder))
    r = a.put("/api/system/backup-schedule", {"enabled": True, "frequency": "DAILY", "time_of_day": "02:00", "weekday": 0,
                                              "destination": str(folder), "keep_daily": 2, "keep_weekly": 1,
                                              "keep_monthly": 1, "passphrase": PASS, "passphrase_confirmation": PASS,
                                              "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert a.post("/api/system/testing/backup-retry").status_code == 409            # nothing failed
    r = a.post("/api/system/testing/backup-schedule", {"due_now": True})
    assert r.status_code == 200, r.text
    from fmpoc.services import scheduled_backup as sb
    runs = sb.tick(app)
    assert len(runs) == 1 and runs[0].result == "SUCCESS"
    when = dt.datetime(2030, 1, 2, 3, 4, tzinfo=dt.timezone.utc)
    v = a.post("/api/system/testing/backup-schedule", {"next_run_at": when.isoformat()}).json()
    assert v["schedule"]["next_run_at"] == "2030-01-02T03:04:00Z"
    run_id = v["runs"][0]["id"]
    v = a.post(f"/api/system/testing/backup-runs/{run_id}/backdate", {"days": 40}).json()
    started = dt.datetime.fromisoformat(v["runs"][0]["started_at"].rstrip("Z"))
    assert dt.datetime.utcnow() - started > dt.timedelta(days=39)
    assert a.post(f"/api/system/testing/backup-runs/{run_id}/backdate", {"days": 0}).status_code == 422
    # the backup-age warning follows the time set here
    old = (dt.datetime.utcnow() - dt.timedelta(days=30)).replace(microsecond=0)
    v = a.post("/api/system/testing/last-backup", {"last_backup_at": old.isoformat() + "Z"}).json()
    assert v["last_backup_overridden"] is True and v["backup_age"]["stale"] is True
    v = a.post("/api/system/testing/last-backup", {"last_backup_at": None}).json()
    assert v["last_backup_overridden"] is False and v["backup_age"]["stale"] is False
    acts = {e["action"] for e in a.get("/api/audit-events?category=SECURITY&page_size=200").json()["items"]}
    assert {"TESTING_BACKUP_SCHEDULE_MOVED", "TESTING_BACKUP_RUN_BACKDATED", "TESTING_LAST_BACKUP_SET"} <= acts
    ev = _events(a, "TESTING_BACKUP_RUN_BACKDATED")[0]
    assert ev["after"]["testing_mode"] is True and ev["after"]["days"] == 40


def test_reminder_cooldown_update_check_and_no_fake_clock(test_server):
    app, a = test_server
    from conftest import _set_roles_directly
    r = a.post("/api/users", {"first_name": "Bea", "last_name": "Manager", "username": "bmanager", "email": "b@example.com",
                              "password": PASSWORD, "display_name": "Bea Manager", "security_domain": "FINANCIAL",
                              "roles": ["BUDGET_MANAGER"]})
    assert r.status_code == 201, r.text
    bm = Api(app)
    bm.login("bmanager")
    _enroll(bm)
    future = (dt.date.today() + dt.timedelta(days=60)).isoformat()
    rem = bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "Board meeting", "due_date": future})
    assert rem.status_code == 201, rem.text
    rid = rem.json()["id"]
    assert bm.get("/api/reminders/count").json()["due"] == 0
    past = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    assert a.post(f"/api/system/testing/reminders/{rid}/due-date", {"due_date": past}).status_code == 200
    assert bm.get("/api/reminders/count").json()["due"] == 1
    assert bm.post("/api/system/testing/reminders/1/due-date", {"due_date": past}).status_code == 403
    # no cooldown yet; the update check can be forced
    assert a.post("/api/system/testing/reinitialize-cooldown/clear").status_code == 409
    r = a.post("/api/system/testing/update-check")
    assert r.status_code == 200 and "request_made" in r.json()
    assert _events(a, "TESTING_UPDATE_CHECK_FORCED")
    assert _set_roles_directly
    # no global fake clock: audit timestamps stay real
    ev = _events(a, "TESTING_REMINDER_MOVED")[0]
    ts = dt.datetime.fromisoformat(ev["timestamp"].rstrip("Z"))
    assert abs((dt.datetime.utcnow() - ts).total_seconds()) < 120


def test_reinitialize_cooldown_cleared(test_server):
    app, a = test_server
    from fmpoc.services import reinitialize as reinit
    from fmpoc.models import AuditEvent, Workspace
    with app.state.session_factory() as db:
        ws = db.query(Workspace).first()
        db.add(AuditEvent(workspace_id=ws.id, action="REINITIALIZE", object_type="workspace", object_id=str(ws.id),
                          category="SECURITY", timestamp=dt.datetime.utcnow()))
        db.commit()
        assert reinit.cooldown_until(db, ws.id) is not None
    r = a.post("/api/system/testing/reinitialize-cooldown/clear")
    assert r.status_code == 200 and r.json()["reinitialize_cooldown_until"] is None
    assert _events(a, "TESTING_REINITIALIZE_COOLDOWN_CLEARED")


def test_testing_backups_marked_and_refused_elsewhere(test_server, env, tmp_path, monkeypatch):
    app, a = test_server
    blob = _backup(type("E", (), {"admin": a})())
    # refused by the app on a server that isn't in testing mode
    j = _restore(env.admin, blob, password=PASSWORD, confirm="RESTORE")
    assert j["state"] == "failed" and "testing mode" in j["error"] and "--accept-testing-backup" in j["error"]
    assert "nothing was changed" in j["error"]
    # ... and in the initialization wizard of a new server
    fresh = create_app(load_settings({"data_dir": str(tmp_path / "fresh")}))
    anon = Api(fresh)
    anon.pre_csrf()
    j = _restore(anon, blob)
    assert j["state"] == "failed" and "testing mode" in j["error"]
    # the command line accepts it with the option, and records it
    from test_v200_cli_restore import run
    p = tmp_path / "t.fmbak"
    p.write_bytes(blob)
    pf = tmp_path / "pass.txt"
    pf.write_text(PASS, encoding="utf-8")
    import fmpoc.cli_restore as cli
    monkeypatch.setattr(cli, "in_container", lambda: False)
    monkeypatch.setattr(cli, "service_installed", lambda: False)
    monkeypatch.setattr(cli, "app_answering", lambda _s: False)
    assert run(env, str(p), "--passphrase-file", str(pf), "--yes") == 2
    assert run(env, str(p), "--passphrase-file", str(pf), "--yes", "--accept-testing-backup") == 0
    import json
    import sqlite3
    con = sqlite3.connect(env.settings.database_path)
    after = con.execute("SELECT after_snapshot FROM audit_event WHERE action = 'SYSTEM_RESTORED' ORDER BY id DESC"
                        ).fetchone()
    con.close()
    assert after and json.loads(after[0])["testing_backup"] is True
    assert _wait
