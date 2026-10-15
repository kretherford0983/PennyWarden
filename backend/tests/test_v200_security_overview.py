"""2.0.0 build 8 (#131): the Administrator's security overview."""
from __future__ import annotations

from dataclasses import replace

from fmpoc import config


def items(client):
    r = client.get("/api/system/security-overview")
    assert r.status_code == 200, r.text
    return {i["key"]: i for i in r.json()["items"]}, r.json()


def test_overview_items_and_roles(env):
    it, d = items(env.admin)
    assert set(it) >= {"https", "two_step", "backup", "locked", "admins", "secure_cookies", "hsts", "trusted_proxies",
                       "disabled"}
    # nobody has two-step in the test data: needs attention, counted by role, no secrets
    assert it["two_step"]["status"] == "attention" and "Register User" in it["two_step"]["note"]
    assert it["admins"]["status"] == "info" and it["admins"]["value"] == "1"
    assert it["locked"]["status"] == "ok" and it["https"]["status"] == "info"     # local install over http
    assert d["attention"] >= 1
    assert env.auditor.get("/api/system/security-overview").status_code == 200
    for c in (env.ru, env.bm, env.bu):
        assert c.get("/api/system/security-overview").status_code == 403
    text = env.admin.get("/api/system/security-overview").text
    assert env.ru.csrf not in text and "password_hash" not in text


def test_plain_http_on_a_network_server_is_flagged(env):
    env.app.state.settings = replace(env.settings, mode="server", host="0.0.0.0")
    it, _ = items(env.admin)
    assert it["https"]["status"] == "attention" and "HTTPS front end" in it["https"]["note"]
    env.app.state.settings = env.settings


def test_locked_accounts_and_stale_backup(env):
    import datetime as dt

    from fmpoc.models import User, Workspace
    with env.app.state.session_factory() as db:
        u = db.query(User).filter(User.username == "reguser").one()
        u.locked_until = dt.datetime.utcnow() + dt.timedelta(hours=1)
        ws = db.query(Workspace).one()
        ws.created_at = ws.bootstrap_completed_at = dt.datetime.utcnow() - dt.timedelta(days=30)
        db.commit()
    it, _ = items(env.admin)
    assert it["locked"]["status"] == "attention" and "reguser" in it["locked"]["note"]
    assert it["backup"]["status"] == "attention"
    env.admin.put("/api/system/backup-age", {"days": 0})
    it, _ = items(env.admin)
    assert it["backup"]["status"] == "info"
