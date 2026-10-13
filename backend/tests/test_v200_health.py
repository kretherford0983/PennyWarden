"""2.0.0 build 6 (#129): the Administrator's health check - sizes, free space, migrations, integrity check."""
from __future__ import annotations

import shutil
from collections import namedtuple



Usage = namedtuple("Usage", "total used free")


def test_health_view(env, base):
    r = env.admin.get("/api/system/health-check")
    assert r.status_code == 200
    h = r.json()
    assert h["database_bytes"] > 0 and h["disk"]["free"] > 0 and h["migrations"]["up_to_date"]
    assert h["thresholds"] == {"free_bytes": 1024 ** 3, "free_percent": 10.0}
    # sizes and counts only: nothing financial
    assert "Acct" not in r.text and "Operations" not in r.text


def test_low_disk_threshold(env, monkeypatch):
    def fake(total, free):
        monkeypatch.setattr(shutil, "disk_usage", lambda _p: Usage(total, total - free, free))
    G = 1024 ** 3
    fake(100 * G, 50 * G)
    assert env.admin.get("/api/system/health-check").json()["low_disk"] is False
    fake(100 * G, 9 * G)            # 9 %: below 10 %
    h = env.admin.get("/api/system/health-check").json()
    assert h["low_disk"] and "Low disk space" in h["low_disk_message"]
    fake(5 * G, int(0.9 * G))       # 18 % but under 1 GB
    assert env.admin.get("/api/system/health-check").json()["low_disk"] is True
    a = env.admin.get("/api/system/backup-schedule/alert").json()
    assert a["low_disk"] and "GB free" in a["low_disk_message"]
    fake(5 * G, 2 * G)
    assert env.admin.get("/api/system/backup-schedule/alert").json()["low_disk"] is False


def test_integrity_check_ok_and_audited(env):
    r = env.admin.post("/api/system/health-check/integrity", {})
    assert r.status_code == 200 and r.json()["ok"] is True
    ev = env.admin.get("/api/audit-events?action=HEALTH_CHECK_RUN").json()["items"][0]
    assert ev["after"]["result"] == "OK"


def test_integrity_failure_exposes_no_internals(env, monkeypatch):
    class Conn:
        def exec_driver_sql(self, _sql):
            class R:
                def fetchall(self):
                    return [("*** in database main *** Page 7: btreeInitPage() returns error code 11",)]
            return R()

    from sqlalchemy.orm import Session
    real = Session.connection
    calls = {"n": 0}

    def fake_connection(self, *a, **k):
        calls["n"] += 1
        return Conn() if calls["n"] == 1 else real(self, *a, **k)
    monkeypatch.setattr(Session, "connection", fake_connection)
    r = env.admin.post("/api/system/health-check/integrity", {})
    monkeypatch.setattr(Session, "connection", real)
    assert r.status_code == 200 and r.json()["ok"] is False
    assert "btree" not in r.text.lower() and "page 7" not in r.text.lower() and "sqlite" not in r.text.lower()
    ev = env.admin.get("/api/audit-events?action=HEALTH_CHECK_RUN").json()["items"][0]
    assert ev["after"]["result"] == "FAILED"


def test_only_administrators(env):
    for c in (env.auditor, env.ru, env.bm, env.bu):
        assert c.get("/api/system/health-check").status_code == 403
        assert c.post("/api/system/health-check/integrity", {}).status_code == 403
    assert env.admin.c.post("/api/system/health-check/integrity", json={}).status_code == 403   # CSRF
