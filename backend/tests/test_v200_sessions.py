"""2.0.0 build 6 (#127): Administrators see active sessions and end them."""
from __future__ import annotations


def sessions(client):
    r = client.get("/api/system/sessions")
    assert r.status_code == 200, r.text
    return r.json()["sessions"]


def by_user(rows, username):
    return [s for s in rows if s["username"] == username]


def test_list_shows_who_is_signed_in_without_identifiers(env):
    rows = sessions(env.admin)
    assert {"admin", "reguser", "budgetmgr", "auditor"} <= {s["username"] for s in rows}
    me = [s for s in rows if s["current"]]
    assert len(me) == 1 and me[0]["username"] == "admin"
    s = by_user(rows, "reguser")[0]
    assert s["signed_in_at"] and s["last_activity_at"] and s["client_ip"] == "testclient"
    # no token, cookie or CSRF value anywhere in the response
    text = env.admin.get("/api/system/sessions").text
    assert env.ru.csrf not in text and "token" not in text.lower()
    for v in env.ru.c.cookies.values():
        assert v not in text
    # Auditors view; nobody else
    a = env.auditor.get("/api/system/sessions")
    assert a.status_code == 200 and a.json()["can_end"] is False
    for c in (env.ru, env.bm, env.bu):
        assert c.get("/api/system/sessions").status_code == 403


def test_end_one_session(env):
    ref = by_user(sessions(env.admin), "reguser")[0]["ref"]
    r = env.admin.post(f"/api/system/sessions/{ref}/end", {})
    assert r.status_code == 200
    assert env.ru.get("/api/auth/me").status_code == 401
    assert not by_user(sessions(env.admin), "reguser")
    ev = env.admin.get("/api/audit-events?action=SESSION_ENDED_BY_ADMIN").json()["items"][0]
    assert ev["after"] == {"username": "reguser", "sessions": 1}
    # own session: use Sign out; unknown ref
    own = [s for s in sessions(env.admin) if s["current"]][0]["ref"]
    assert env.admin.post(f"/api/system/sessions/{own}/end", {}).json()["error"]["code"] == "OWN_SESSION"
    assert env.admin.post("/api/system/sessions/999999/end", {}).status_code == 404


def test_end_user_and_end_everyone(env):
    uid = by_user(sessions(env.admin), "budgetmgr")[0]["user_id"]
    r = env.admin.post("/api/system/sessions/end-user", {"user_id": uid})
    assert r.status_code == 200 and r.json()["ended"] == 1
    assert env.bm.get("/api/auth/me").status_code == 401
    r = env.admin.post("/api/system/sessions/end-all", {})
    assert r.status_code == 200 and r.json()["ended"] >= 3
    for c in (env.ru, env.bu, env.auditor):
        assert c.get("/api/auth/me").status_code == 401
    assert env.admin.get("/api/auth/me").status_code == 200       # the Administrator's own session remains
    assert [s["username"] for s in sessions(env.admin)] == ["admin"]
    ev = env.admin.get("/api/audit-events?action=ALL_SESSIONS_ENDED_BY_ADMIN").json()["items"][0]
    assert ev["category"] == "SECURITY" and ev["after"]["sessions"] >= 3


def test_only_administrators_end_sessions(env):
    ref = by_user(sessions(env.admin), "reguser")[0]["ref"]
    uid = by_user(sessions(env.admin), "reguser")[0]["user_id"]
    for c in (env.auditor, env.bm, env.ru):
        assert c.post(f"/api/system/sessions/{ref}/end", {}).status_code == 403
        assert c.post("/api/system/sessions/end-user", {"user_id": uid}).status_code == 403
        assert c.post("/api/system/sessions/end-all", {}).status_code == 403
    assert env.ru.get("/api/auth/me").status_code == 200
    # CSRF is required like every change
    r = env.admin.c.post(f"/api/system/sessions/{ref}/end", json={})
    assert r.status_code == 403
