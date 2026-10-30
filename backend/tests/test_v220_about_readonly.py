"""2.2.0 (#349): System/About read-only for the financial roles (and General for Auditors) - version, update-check
result, organization details and module status. Every change stays the Administrator's; no network details, no
backup notice, no Check now."""
from __future__ import annotations


def test_financial_roles_read_about_and_general(env, base):
    for c in (env.bm, env.bu, env.ru, env.auditor):
        assert "system.about" in c.get("/api/auth/me").json()["permissions"]
        assert c.get("/api/system/organization").status_code == 200
        assert c.get("/api/system/modules/status").status_code == 200
        assert c.get("/api/updates").status_code == 200
    for c in (env.bm, env.bu, env.ru):
        a = c.get("/api/system/about").json()
        assert a["version"] and a["bind_host"] is None and a["port"] is None
        assert a["backup_notice"] is None and a["restore_max_mb"] is None        # backups are the Administrator's
    assert env.auditor.get("/api/system/about").json()["backup_notice"]
    assert env.admin.get("/api/system/about").json()["backup_notice"]


def test_changes_stay_with_administrators(env, base):
    for c in (env.bm, env.bu, env.ru, env.auditor):
        assert c.put("/api/system/organization", {"name": "Hijack"}).status_code == 403
        assert c.get("/api/system/modules").status_code == 403                    # the editor's view
        assert c.put("/api/system/modules", {"checks": True}).status_code == 403
        assert c.put("/api/updates/settings", {"enabled": False}).status_code == 403
        assert c.post("/api/updates/check").status_code == 403                    # no Check now
    for c in (env.bm, env.bu, env.ru):
        for path in ("/api/system/settings", "/api/system/sessions", "/api/system/security-overview",
                     "/api/system/backup-age", "/api/system/health-check", "/api/system/maintenance"):
            assert c.get(path).status_code == 403, path


def test_module_status_lists_every_module_and_the_viewers_access(env, base):
    assert env.admin.put("/api/system/modules", {"checks": True}).status_code == 200
    rows = {m["key"]: m for m in env.ru.get("/api/system/modules/status").json()}
    assert list(rows) == ["fundraisers", "checks", "donations"]
    assert rows["checks"]["enabled"] is True and rows["checks"]["name"] == "Payments"
    assert rows["checks"]["used_by"] == ["Register Users", "Administrators (setup)"]
    assert rows["donations"]["enabled"] is False
    assert rows["fundraisers"]["used_by"] == ["Budget Managers", "Budget Users", "Register Users", "Auditors"]
    assert rows["checks"]["you"] is True and rows["fundraisers"]["you"] is True
    bm = {m["key"]: m for m in env.bm.get("/api/system/modules/status").json()}
    assert bm["checks"]["you"] is False and bm["donations"]["you"] is True
    adm = {m["key"]: m for m in env.admin.get("/api/system/modules/status").json()}
    assert adm["checks"]["you"] is True and adm["fundraisers"]["you"] is False
