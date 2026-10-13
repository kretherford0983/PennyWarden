"""Initialization, authentication, sessions, CSRF, password change and theme.
AC-SEC-001, AC-SEC-002, AC-SEC-006, AC-SEC-020, AC-SEC-022, AC-INIT-001..008, AC-AUTH-SELF-001..006,
AC-UI-THEME-001/002 (API persistence)."""
import sqlite3

from conftest import ADMIN, PASSWORD, Api, initialize

from fmpoc.app import create_app
from fmpoc.config import load_settings


def test_ac_init_001_008_fresh_install_requires_wizard(anon, settings):
    # AC-INIT-001 / AC-INIT-008: migrations created an (empty) database, but the app is still uninitialized.
    assert settings.database_path.exists()
    st = anon.get("/api/system/status").json()
    assert st["initialized"] is False
    # AC-SEC-001 / AC-SEC-022: no default credentials exist
    anon.pre_csrf()
    for u, p in [("admin", "admin"), ("admin", "password"), ("administrator", "admin")]:
        assert anon.post("/api/auth/login", {"username": u, "password": p}).status_code == 401


def test_ac_init_008_partial_workspace_row_does_not_suppress_wizard(settings, tmp_path):
    app = create_app(settings)
    con = sqlite3.connect(settings.database_path)
    con.execute("INSERT INTO workspace (name, created_at, next_entity_number) VALUES ('partial', '2026-01-01', 1)")
    con.commit()
    con.close()
    a = Api(app)
    assert a.get("/api/system/status").json()["initialized"] is False
    initialize(app)
    assert a.get("/api/system/status").json()["initialized"] is True


def test_ac_init_002_required_fields(anon):
    anon.pre_csrf()
    for missing in ["workspace_name", "admin_username", "admin_email", "password", "password_confirmation",
                    "admin_first_name", "admin_last_name"]:
        body = {k: v for k, v in ADMIN.items() if k != missing}
        r = anon.post("/api/system/initialize", body)
        assert r.status_code == 422, missing
    bad = dict(ADMIN, admin_email="not-an-email")
    assert anon.post("/api/system/initialize", bad).status_code == 422
    mismatch = dict(ADMIN, password_confirmation=PASSWORD + "x")
    assert anon.post("/api/system/initialize", mismatch).status_code == 422
    weak = dict(ADMIN, password="short1", password_confirmation="short1")
    assert anon.post("/api/system/initialize", weak).status_code == 422
    assert anon.get("/api/system/status").json()["initialized"] is False


def test_ac_init_003_to_007_bootstrap_admin(app, settings):
    admin = initialize(app)
    # AC-INIT-003: key, roles and seed records
    assert (settings.secrets_dir / "portable-encryption-key.json").is_file()
    # AC-INIT-004: can log in immediately with a fresh session
    fresh = Api(app)
    r = fresh.login("admin")
    assert r.status_code == 200
    me = r.json()
    assert me["security_domain"] == "ADMINISTRATOR" and me["roles"] == ["ADMINISTRATOR"]
    # AC-INIT-005: admin screens/dashboard
    assert fresh.get("/api/dashboard").json()["kind"] == "administrator"
    assert fresh.get("/api/users").status_code == 200
    assert fresh.get("/api/audit-events").status_code == 200
    assert fresh.get("/api/system/about").status_code == 200
    # AC-INIT-006: in user list with Administrator role and email
    users = fresh.get("/api/users").json()
    assert any(u["username"] == "admin" and u["roles"] == ["ADMINISTRATOR"] and u["email"] == "admin@example.com"
               for u in users)
    # AC-INIT-007: no financial modules
    for url in ["/api/fiscal-years", "/api/entities", "/api/bank-accounts", "/api/register"]:
        assert fresh.get(url).status_code == 403, url
    # re-initialization is refused
    admin.pre_csrf()
    other = Api(app)
    other.pre_csrf()
    assert other.post("/api/system/initialize", ADMIN).status_code == 409
    # audit event for initialization
    ev = fresh.get("/api/audit-events?action=SYSTEM_INITIALIZED").json()["items"]
    assert ev and "password" not in str(ev)


def test_ac_sec_002_domain_separation(env):
    bad = [("ADMINISTRATOR", ["ADMINISTRATOR", "BUDGET_MANAGER"]), ("AUDITOR", ["AUDITOR", "REGISTER_USER"]),
           ("ADMINISTRATOR", ["ADMINISTRATOR", "AUDITOR"]), ("FINANCIAL", ["BUDGET_MANAGER", "AUDITOR"]),
           ("FINANCIAL", ["ADMINISTRATOR"]), ("AUDITOR", ["BUDGET_USER"])]
    for i, (dom, roles) in enumerate(bad):
        r = env.admin.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": f"bad{i}", "email": f"b{i}@x.org", "password": PASSWORD,
                                          "display_name": f"Bad Roles {i}",
                                          "security_domain": dom, "roles": roles})
        assert r.status_code == 422 and r.json()["error"]["errors"][0]["field"] == "roles", (dom, roles, r.text)
    r = env.admin.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "multi", "email": "m@x.org", "password": PASSWORD,
                                      "display_name": "Multi Role",
                                      "security_domain": "FINANCIAL",
                                      "roles": ["BUDGET_MANAGER", "BUDGET_USER", "REGISTER_USER"]})
    assert r.status_code == 201
    uid = r.json()["id"]
    # role changes also cannot cross domains
    assert env.admin.patch(f"/api/users/{uid}", {"roles": ["BUDGET_MANAGER", "AUDITOR"]}).status_code == 422
    assert env.admin.patch(f"/api/users/{uid}", {"security_domain": "AUDITOR", "roles": ["AUDITOR"]}).status_code == 200


def test_ac_sec_006_session_cookie_properties(app):
    a = initialize(app)
    b = Api(app)
    b.pre_csrf()
    r = b.post("/api/auth/login", {"username": "admin", "password": PASSWORD})
    sc = r.headers.get("set-cookie", "")
    assert "fm_session=" in sc and "HttpOnly" in sc and "SameSite=strict" in sc.replace("Strict", "strict")
    # auth token is not in the JSON body (nothing for the SPA to put in localStorage)
    assert "fm_session" not in r.text
    token = b.c.cookies.get("fm_session")
    assert token and token not in r.text
    # server-side session: logout invalidates it even if the cookie is replayed
    b.csrf = r.json()["csrf_token"]
    assert b.post("/api/auth/logout").status_code == 200
    replay = Api(app)
    replay.c.cookies.set("fm_session", token)
    assert replay.get("/api/auth/me").status_code == 401
    assert a.get("/api/auth/me").status_code == 200


def test_ac_sec_006_session_rotation_on_login(app):
    initialize(app)
    a = Api(app)
    a.login("admin")
    t1 = a.c.cookies.get("fm_session")
    a.pre_csrf()
    a.post("/api/auth/login", {"username": "admin", "password": PASSWORD})
    t2 = a.c.cookies.get("fm_session")
    assert t1 != t2
    old = Api(app)
    old.c.cookies.set("fm_session", t1)
    assert old.get("/api/auth/me").status_code == 401


def test_ac_sec_020_csrf_rejection_no_mutation(env, base):
    # missing token
    r = env.bm.c.post("/api/fiscal-years", json={"identifier": "2099", "start_date": "2099-01-01",
                                                  "end_date": "2099-12-31"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_FAILED"
    # wrong token
    r = env.bm.c.post("/api/fiscal-years", json={"identifier": "2099", "start_date": "2099-01-01",
                                                  "end_date": "2099-12-31"}, headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    # another user's token
    r = env.bm.c.post("/api/fiscal-years", json={"identifier": "2099", "start_date": "2099-01-01",
                                                  "end_date": "2099-12-31"}, headers={"X-CSRF-Token": env.ru.csrf})
    assert r.status_code == 403
    # cross-origin request with a valid token is also rejected
    r = env.bm.post("/api/fiscal-years", {"identifier": "2099", "start_date": "2099-01-01", "end_date": "2099-12-31"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert all(f["identifier"] != "2099" for f in env.bm.get("/api/fiscal-years").json())
    # login without the pre-auth token is rejected too
    x = Api(env.app)
    assert x.c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code == 403


def test_ac_sec_020_every_mutating_route_requires_csrf(env):
    """Enumerate every state-changing API route and verify CSRF enforcement without a token."""
    from fastapi.routing import APIRoute
    routes = []
    for r in env.app.router.routes:
        stack = [r]
        while stack:
            x = stack.pop()
            if isinstance(x, APIRoute):
                routes.append(x)
            for attr in ("original_router", "routes"):
                sub = getattr(x, attr, None)
                if sub is not None:
                    stack.extend(sub.routes if hasattr(sub, "routes") else sub)
    checked = 0
    for route in routes:
        for m in route.methods - {"GET", "HEAD", "OPTIONS"}:
            if "{rest" in route.path:
                continue
            url = route.path.replace("{", "").replace("}", "")
            for p in ["fy_id", "budget_id", "entity_id", "account_id", "txn_id", "att_id", "user_id", "review_id"]:
                url = url.replace(p, "1")
            resp = env.bm.c.request(m, url, json={})
            assert resp.status_code in (403,), (m, route.path, resp.status_code)
            checked += 1
    assert checked >= 25


def test_ac_auth_self_001_to_006_password_change(env):
    other_session = Api(env.app)
    assert other_session.login("reguser").status_code == 200
    # AC-AUTH-SELF-002 incorrect current password
    r = env.ru.post("/api/auth/change-password", {"current_password": "wrong-password-1", "new_password": "New-Password-123",
                                                   "new_password_confirmation": "New-Password-123"})
    assert r.status_code == 400
    # AC-AUTH-SELF-003 policy
    r = env.ru.post("/api/auth/change-password", {"current_password": PASSWORD, "new_password": "short",
                                                   "new_password_confirmation": "short"})
    assert r.status_code == 422
    r = env.ru.post("/api/auth/change-password", {"current_password": PASSWORD, "new_password": "New-Password-123",
                                                   "new_password_confirmation": "Different-123456"})
    assert r.status_code == 422
    # AC-AUTH-SELF-001 success
    r = env.ru.post("/api/auth/change-password", {"current_password": PASSWORD, "new_password": "New-Password-123",
                                                   "new_password_confirmation": "New-Password-123"})
    assert r.status_code == 200
    assert env.ru.get("/api/auth/me").status_code == 200  # current session kept
    # AC-AUTH-SELF-005 other sessions invalidated
    assert other_session.get("/api/auth/me").status_code == 401
    # AC-AUTH-SELF-004 old fails, new works
    assert Api(env.app).login("reguser", PASSWORD).status_code == 401
    assert Api(env.app).login("reguser", "New-Password-123").status_code == 200
    # AC-AUTH-SELF-006 audit without password values
    ev = env.admin.get("/api/audit-events?action=PASSWORD_CHANGED").json()["items"]
    assert ev
    dump = str(env.admin.get("/api/audit-events?limit=500").json())
    assert "New-Password-123" not in dump and PASSWORD not in dump and "argon2" not in dump


def test_ac_auth_self_all_domains_can_change_password(env):
    for client, name in [(env.admin, "admin"), (env.auditor, "auditor"), (env.bm, "budgetmgr"), (env.bu, "budgetuser")]:
        r = client.post("/api/auth/change-password", {"current_password": PASSWORD, "new_password": "Another-Pass-777",
                                                       "new_password_confirmation": "Another-Pass-777"})
        assert r.status_code == 200, name


def test_ac_ui_theme_001_002_persistence(env):
    assert env.bu.get("/api/auth/me").json()["theme"] == "light"
    assert env.bu.put("/api/me/preferences", {"theme": "dark"}).status_code == 200
    assert env.bu.put("/api/me/preferences", {"theme": "purple"}).status_code == 422
    env.bu.post("/api/auth/logout")
    again = Api(env.app)
    assert again.login("budgetuser").json()["theme"] == "dark"


def test_failed_login_rate_limiting_and_audit(env):
    x = Api(env.app)
    x.pre_csrf()
    for _ in range(5):
        assert x.post("/api/auth/login", {"username": "reguser", "password": "bad-password-xx"}).status_code == 401
    assert x.post("/api/auth/login", {"username": "reguser", "password": PASSWORD}).status_code == 429
    ev = env.admin.get("/api/audit-events?action=LOGIN_FAILED").json()["items"]
    assert len(ev) >= 5 and "bad-password-xx" not in str(ev)


def test_disabled_user_loses_authorization(env):
    uid = next(u["id"] for u in env.admin.get("/api/users").json() if u["username"] == "reguser")
    assert env.admin.patch(f"/api/users/{uid}", {"active": False}).status_code == 200
    assert env.ru.get("/api/auth/me").status_code == 401
    assert Api(env.app).login("reguser").status_code == 401


def test_last_administrator_cannot_be_disabled(env):
    uid = next(u["id"] for u in env.admin.get("/api/users").json() if u["username"] == "admin")
    # 1.7.2: refused even earlier - nobody can disable their own account (the only way to disable the last one)
    r = env.admin.patch(f"/api/users/{uid}", {"active": False})
    assert r.status_code == 403 and r.json()["error"]["code"] == "OWN_ACCOUNT_DISABLE"
    assert env.admin.get("/api/auth/me").status_code == 200


def test_admin_password_reset_audited(env):
    uid = next(u["id"] for u in env.admin.get("/api/users").json() if u["username"] == "budgetuser")
    assert env.admin.post(f"/api/users/{uid}/reset-password", {"new_password": "Reset-Password-42"}).status_code == 200
    assert env.bu.get("/api/auth/me").status_code == 401
    assert Api(env.app).login("budgetuser", "Reset-Password-42").status_code == 200


def test_ac_sec_022_no_debug_or_docs_exposed(anon):
    for url in ["/docs", "/redoc", "/openapi.json", "/api/docs"]:
        r = anon.get(url)
        assert r.status_code in (404, 200)
        assert "swagger" not in r.text.lower() and '"openapi"' not in r.text


def test_settings_local_mode_binds_loopback(tmp_path, monkeypatch):
    """AC-DEP-003 (bind default) / AC-DEP-004 (server mode configurable)."""
    s = load_settings({"data_dir": str(tmp_path)})
    assert s.mode == "local" and s.host == "127.0.0.1"
    monkeypatch.setenv("FM_MODE", "server")
    monkeypatch.setenv("FM_HOST", "0.0.0.0")
    s2 = load_settings({"data_dir": str(tmp_path)})
    assert s2.mode == "server" and s2.host == "0.0.0.0"
