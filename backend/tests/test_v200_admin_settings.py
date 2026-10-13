"""2.0.0 build 6 (#126): effective settings, the server settings editor, organization rename, backup age warning."""
from __future__ import annotations

import datetime as dt
import tomllib
from dataclasses import replace

import pytest

from fmpoc import config
from fmpoc.services import admin_settings as adm

CFG = """# PennyWarden server settings - keep this comment
[server]
mode = "server"   # the mode
host = "0.0.0.0"
session_idle_minutes = 30
# a comment in the middle
hsts = false
unknown_key = "kept"

[other]
x = 1
"""


@pytest.fixture
def server(env, monkeypatch):
    """The test app switched to server mode at run time (the sessions are already set up)."""
    (env.settings.data_dir / "config.toml").write_text(CFG, encoding="utf-8")
    for k in list(__import__("os").environ):
        if k.startswith("FM_"):
            monkeypatch.delenv(k)
    s = config.load_settings({"data_dir": str(env.settings.data_dir), "login_max_failures": 5})
    env.app.state.settings = s
    return env


def rows(r):
    return {x["name"]: x for x in r.json()["settings"]}


# ------------------------------------------------------------------ toml rewriting
def test_rewrite_keeps_comments_unknown_keys_and_tables():
    out = adm.rewrite_toml(CFG, {"session_idle_minutes": 20, "hsts": True, "trusted_proxies": "10.0.0.1"})
    assert "# PennyWarden server settings - keep this comment" in out and "# a comment in the middle" in out
    assert 'unknown_key = "kept"' in out and "[other]" in out and 'mode = "server"   # the mode' in out
    d = tomllib.loads(out)
    assert d["server"]["session_idle_minutes"] == 20 and d["server"]["hsts"] is True
    assert d["server"]["trusted_proxies"] == "10.0.0.1" and d["other"] == {"x": 1}
    # the new key goes into [server], not into [other]
    assert out.index("trusted_proxies") < out.index("[other]")
    # no [server] table yet, or no file at all
    assert tomllib.loads(adm.rewrite_toml("[other]\nx = 1\n", {"hsts": True}))["server"] == {"hsts": True}
    assert tomllib.loads(adm.rewrite_toml("", {"hsts": True})) == {"server": {"hsts": True}}
    # strings are escaped
    assert tomllib.loads(adm.rewrite_toml("", {"log_level": 'a"b\\c'}))["server"]["log_level"] == 'a"b\\c'


# ------------------------------------------------------------------ effective settings view
def test_effective_view_sources_and_who_sees_it(server, monkeypatch):
    env = server
    monkeypatch.setenv("FM_HSTS", "true")
    r = env.admin.get("/api/system/settings")
    assert r.status_code == 200
    s = rows(r)
    assert s["session_idle_minutes"]["source"] == "config.toml" and s["session_idle_minutes"]["editable"]
    assert s["hsts"]["source"] == "environment" and s["hsts"]["locked"] and not s["hsts"]["editable"]
    assert s["login_max_failures"]["source"] == "command line" and s["login_max_failures"]["locked"]
    assert s["log_level"]["source"] == "default"
    for ro in ("host", "port", "mode", "data_dir"):
        assert not s[ro]["editable"] and s[ro]["read_only_reason"]
    assert "frontend_dir" not in s and r.json()["editor"] is True
    # Auditors: the same view, nothing editable
    a = env.auditor.get("/api/system/settings")
    assert a.status_code == 200 and a.json()["editor"] is False
    assert not any(x["editable"] for x in a.json()["settings"])
    for c in (env.ru, env.bm, env.bu):
        assert c.get("/api/system/settings").status_code == 403


def test_local_mode_has_the_view_but_no_editor(env):
    r = env.admin.get("/api/system/settings")
    assert r.status_code == 200 and r.json()["editor"] is False and r.json()["mode"] == "local"
    r = env.admin.put("/api/system/settings", {"changes": {"session_idle_minutes": 20}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SERVER_ONLY"


# ------------------------------------------------------------------ editor
def test_save_writes_atomically_keeps_backup_and_needs_restart(server):
    env = server
    path = env.settings.data_dir / "config.toml"
    r = env.admin.put("/api/system/settings", {"changes": {"session_idle_minutes": 20, "hsts": True}})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == ["hsts", "session_idle_minutes"] and r.json()["restart_required"]
    s = rows(r)
    assert s["session_idle_minutes"]["restart_required"] and s["session_idle_minutes"]["value"] == 30
    assert s["session_idle_minutes"]["saved_value"] == 20
    text = path.read_text(encoding="utf-8")
    assert "# a comment in the middle" in text and tomllib.loads(text)["server"]["hsts"] is True
    assert (env.settings.data_dir / "config.toml.bak").read_text(encoding="utf-8") == CFG
    ev = env.admin.get("/api/audit-events?action=SERVER_SETTINGS_CHANGED").json()["items"][0]
    assert ev["before"] == {"session_idle_minutes": 30, "hsts": False}
    assert ev["after"] == {"session_idle_minutes": 20, "hsts": True}
    # after a restart (new settings from the file) nothing is pending
    env.app.state.settings = config.load_settings({"data_dir": str(env.settings.data_dir), "login_max_failures": 5})
    assert env.admin.get("/api/system/settings").json()["restart_required"] is False
    # saving the same values changes nothing
    r = env.admin.put("/api/system/settings", {"changes": {"session_idle_minutes": 20}})
    assert r.json()["changed"] == []


@pytest.mark.parametrize("changes", [
    {"port": 9000}, {"host": "0.0.0.0"}, {"mode": "local"}, {"data_dir": "/tmp/x"}, {"debug": True},
    {"session_idle_minutes": 0}, {"session_idle_minutes": 100000}, {"session_idle_minutes": "20"},
    {"lockout_1_failures": 12}, {"secure_cookies": "maybe"}, {"log_level": "TRACE"}, {"hsts": "yes"},
    {"trusted_proxies": "not-an-ip"}, {"session_idle_minutes": 200, "session_absolute_hours": 2},
])
def test_invalid_or_disallowed_changes_write_nothing(server, changes):
    env = server
    path = env.settings.data_dir / "config.toml"
    r = env.admin.put("/api/system/settings", {"changes": changes, "password": "x"})
    assert r.status_code == 422, r.text
    assert path.read_text(encoding="utf-8") == CFG


def test_locked_settings_and_roles(server, monkeypatch):
    env = server
    monkeypatch.setenv("FM_SESSION_IDLE_MINUTES", "15")
    r = env.admin.put("/api/system/settings", {"changes": {"session_idle_minutes": 20}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SETTING_LOCKED"
    r = env.admin.put("/api/system/settings", {"changes": {"login_max_failures": 6}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SETTING_LOCKED"
    for c in (env.auditor, env.ru, env.bm):
        assert c.put("/api/system/settings", {"changes": {"hsts": True}}).status_code == 403
    # mass assignment: unknown fields are refused by the schema
    assert env.admin.put("/api/system/settings", {"changes": {"hsts": True}, "mode": "local"}).status_code == 422


def test_weakening_needs_confirmation_and_proxies_need_the_password(server):
    from conftest import ADMIN
    env = server
    r = env.admin.put("/api/system/settings", {"changes": {"session_idle_minutes": 45, "secure_cookies": "false"}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert "Secure cookies off" in r.json()["error"]["warnings"][0]["message"]
    r = env.admin.put("/api/system/settings", {"changes": {"session_idle_minutes": 45, "secure_cookies": "false"},
                                               "confirmations": ["SECURITY_WEAKENING"]})
    assert r.status_code == 200
    # stricter changes need no confirmation
    assert env.admin.put("/api/system/settings", {"changes": {"session_idle_minutes": 25}}).status_code == 200
    # trusted proxies: the password
    body = {"changes": {"trusted_proxies": "10.0.0.5, 192.168.1.0/24"}, "confirmations": ["SECURITY_WEAKENING"]}
    r = env.admin.put("/api/system/settings", {**body, "password": "wrong"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INCORRECT_PASSWORD"
    assert env.admin.get("/api/audit-events?action=SERVER_SETTINGS_DENIED").json()["items"]
    r = env.admin.put("/api/system/settings", {**body, "password": ADMIN["password"]})
    assert r.status_code == 200, r.text
    assert rows(r)["trusted_proxies"]["saved_value"] == "10.0.0.5, 192.168.1.0/24"


def test_unreadable_config_is_left_alone(server):
    env = server
    path = env.settings.data_dir / "config.toml"
    path.write_text("[server\nbroken", encoding="utf-8")
    r = env.admin.put("/api/system/settings", {"changes": {"hsts": True}})
    assert r.status_code == 409 and path.read_text(encoding="utf-8") == "[server\nbroken"


# ------------------------------------------------------------------ organization name
def test_rename_organization(env):
    r = env.admin.put("/api/system/organization", {"name": "  Sample Organization Renamed  "})
    assert r.status_code == 200 and r.json()["name"] == "Sample Organization Renamed"
    assert env.admin.get("/api/system/status").json()["workspace_name"] == "Sample Organization Renamed"
    ev = env.admin.get("/api/audit-events?action=ORGANIZATION_RENAMED").json()["items"][0]
    assert ev["before"] == {"name": "Acme Org"} and ev["after"] == {"name": "Sample Organization Renamed"}
    for bad in ("", "   ", "x" * 121, "bad\x07name"):
        assert env.admin.put("/api/system/organization", {"name": bad}).status_code == 422
    for c in (env.auditor, env.ru, env.bm, env.bu):
        assert c.put("/api/system/organization", {"name": "Hijack"}).status_code == 403


# ------------------------------------------------------------------ backup age warning
def test_backup_age_warning(env):
    from fmpoc.models import AuditEvent, Workspace
    r = env.admin.get("/api/system/backup-age")
    assert r.status_code == 200 and r.json()["warning_days"] == 7 and r.json()["stale"] is False
    with env.app.state.session_factory() as db:
        ws = db.query(Workspace).one()
        old = dt.datetime.utcnow() - dt.timedelta(days=10)
        ws.created_at = ws.bootstrap_completed_at = old
        db.commit()
    a = env.admin.get("/api/system/backup-schedule/alert").json()
    assert a["stale"] and "No backup has been made on this installation yet" in a["stale_message"]
    # a backup clears it
    with env.app.state.session_factory() as db:
        db.add(AuditEvent(workspace_id=ws.id, action="BACKUP_CREATED", object_type="workspace"))
        db.commit()
    assert env.admin.get("/api/system/backup-age").json()["stale"] is False
    # the threshold: 0 turns it off; limits; Administrators only
    r = env.admin.put("/api/system/backup-age", {"days": 0})
    assert r.status_code == 200 and r.json()["warning_days"] == 0
    assert env.admin.put("/api/system/backup-age", {"days": 366}).status_code == 422
    assert env.admin.get("/api/audit-events?action=BACKUP_WARNING_CHANGED").json()["items"]
    for c in (env.auditor, env.ru):
        assert c.put("/api/system/backup-age", {"days": 3}).status_code == 403
        assert c.get("/api/system/backup-age").status_code == 403

