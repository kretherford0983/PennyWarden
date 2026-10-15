"""2.0.0 build 8 (#134): first and last names on every account, the completion step, search, and the audit actor."""
from __future__ import annotations

from conftest import ADMIN, PASSWORD


def new_user(env, username, **extra):
    body = {"username": username, "email": f"{username}@example.com", "display_name": f"{username} display",
            "password": PASSWORD, "security_domain": "FINANCIAL", "roles": ["BUDGET_USER"],
            "first_name": "John", "last_name": "Smith"}
    body.update(extra)
    return env.admin.post("/api/users", body)


def test_names_required_and_validated(env):
    for missing in ("first_name", "last_name"):
        r = new_user(env, "pw00001", **{missing: None})
        assert r.status_code == 422 and r.json()["error"]["errors"][0]["field"] == missing
        assert new_user(env, "pw00001", **{missing: "   "}).status_code == 422
    assert new_user(env, "pw00001", first_name="x" * 61).status_code == 422
    assert new_user(env, "pw00001", first_name="123").status_code == 422
    r = new_user(env, "pw00001", first_name="  Zoë  ", last_name="O'Brien-Núñez")
    assert r.status_code == 201
    u = r.json()
    assert (u["first_name"], u["last_name"], u["label"]) == ("Zoë", "O'Brien-Núñez", "Zoë O'Brien-Núñez - pw00001")
    # markup is stored as plain text (the UI renders text, never HTML)
    r = new_user(env, "pw00002", first_name="<b>Jo</b>", last_name="Smith")
    assert r.status_code == 201 and r.json()["first_name"] == "<b>Jo</b>"
    # editing: names can be corrected, never removed
    uid = u["id"]
    assert env.admin.patch(f"/api/users/{uid}", {"first_name": ""}).status_code == 422
    r = env.admin.patch(f"/api/users/{uid}", {"first_name": "Zoe"})
    assert r.status_code == 200 and r.json()["first_name"] == "Zoe"
    ev = env.admin.get(f"/api/audit-events?action=USER_UPDATED&object_id={uid}").json()["items"][0]
    assert ev["before"]["first_name"] == "Zoë" and ev["after"]["first_name"] == "Zoe"


def test_only_administrators_change_names(env):
    uid = new_user(env, "pw00003").json()["id"]
    for c in (env.bm, env.ru, env.auditor):
        assert c.patch(f"/api/users/{uid}", {"first_name": "Hijack"}).status_code == 403
    # nobody edits their own names on My account
    assert env.ru.put("/api/me/preferences", {"first_name": "Me"}).status_code == 422
    me = env.admin.get("/api/auth/me").json()
    assert me["first_name"] == "Pat" and me["names_needed"] == 0
    # an Administrator may correct their own names (but not their own roles on a server - unchanged)
    assert env.admin.patch(f"/api/users/{me['id']}", {"last_name": "Examples"}).status_code == 200
    # mass assignment
    assert env.admin.patch(f"/api/users/{uid}", {"first_name": "A", "password_hash": "x"}).status_code == 422


def test_search_fields_and_sort_are_in_the_list(env):
    for i, (first, last) in enumerate((("John", "Smith"), ("John", "Stone"), ("John", "Adams"), ("Jon", "Smith"))):
        assert new_user(env, f"pw0001{i}", first_name=first, last_name=last).status_code == 201
    users = env.auditor.get("/api/users").json()
    smiths = [u for u in users if "smith" in " ".join(str(u.get(k) or "") for k in
                                                   ("first_name", "last_name", "username", "display_name", "email")).lower()]
    assert {u["username"] for u in smiths} == {"pw00010", "pw00013"}
    assert all("first_name" in u and "name_needed" in u for u in users)


def _strip_names(env, *usernames):
    from fmpoc.models import User
    with env.app.state.session_factory() as db:
        for u in db.query(User).filter(User.username.in_(usernames)):
            u.first_name = u.last_name = None
        db.commit()


def test_completion_step_after_the_upgrade(env):
    _strip_names(env, "reguser", "budgetmgr")
    env.admin.patch(f"/api/users/{[u for u in env.admin.get('/api/users').json() if u['username'] == 'budgetmgr'][0]['id']}",
                    {"first_name": "Bea", "last_name": "Manager", "active": False})
    _strip_names(env, "budgetmgr")      # an inactive account without names is listed too
    me = env.admin.get("/api/auth/me").json()
    assert me["names_needed"] == 2
    rows = env.admin.get("/api/users/names-needed").json()
    assert {r["username"] for r in rows} == {"reguser", "budgetmgr"}
    assert {r["active"] for r in rows} == {True, False}
    # other users keep working; the list marks them
    assert env.ru.get("/api/auth/me").status_code == 200
    listed = {u["username"]: u for u in env.auditor.get("/api/users").json()}
    assert listed["reguser"]["name_needed"] is True
    # an edit of such an account must add the names
    assert env.admin.patch(f"/api/users/{rows[0]['id']}", {"email": "x@example.com"}).status_code == 422
    # all rows are checked before any is saved
    bad = [{"id": r["id"], "first_name": "Rae", "last_name": ""} for r in rows]
    assert env.admin.put("/api/users/names", {"users": bad}).status_code == 422
    assert env.admin.get("/api/auth/me").json()["names_needed"] == 2
    ok = [{"id": r["id"], "first_name": r["display_name"].split()[0], "last_name": "Stand-in"} for r in rows]
    r = env.admin.put("/api/users/names", {"users": ok})
    assert r.status_code == 200 and r.json() == {"updated": 2, "remaining": 0}
    assert env.admin.get("/api/auth/me").json()["names_needed"] == 0
    assert env.admin.put("/api/users/names", {"users": ok}).status_code == 422     # nothing left to complete
    for c in (env.ru, env.auditor):
        assert c.get("/api/users/names-needed").status_code == 403
        assert c.put("/api/users/names", {"users": ok}).status_code == 403
    # non-Administrators never see the step
    assert env.ru.get("/api/auth/me").json()["names_needed"] == 0


def test_audit_actor_name_at_the_time(env):
    uid = new_user(env, "pw00020").json()["id"]
    ev = env.admin.get(f"/api/audit-events?action=USER_CREATED&object_id={uid}").json()["items"][0]
    assert ev["actor_name"] == "Pat Example" and ev["actor_username"] == "admin"
    me = env.admin.get("/api/auth/me").json()
    env.admin.patch(f"/api/users/{me['id']}", {"first_name": "Patricia"})
    ev2 = env.admin.get(f"/api/audit-events?action=USER_CREATED&object_id={uid}").json()["items"][0]
    assert ev2["actor_name"] == "Pat Example"                                # history keeps the earlier name
    new_user(env, "pw00021")
    ev3 = env.admin.get("/api/audit-events?action=USER_CREATED").json()["items"][0]
    assert ev3["actor_name"] == "Patricia Example"


def test_wizard_requires_the_names(app, anon):
    anon.pre_csrf()
    for k, label in (("admin_first_name", "First name"), ("admin_last_name", "Last name")):
        r = anon.post("/api/system/initialize", {**ADMIN, k: " "})
        assert r.status_code == 422
        # 2.0.0 build 13: the wizard's first-name field said "Last name is required."
        assert r.json()["error"]["errors"] == [{"field": k, "message": f"{label} is required."}]
    assert anon.post("/api/system/initialize", ADMIN).status_code == 200
    from fmpoc.models import User
    with app.state.session_factory() as db:
        u = db.query(User).one()
        assert (u.first_name, u.last_name) == ("Pat", "Example")
