"""1.7.1 (#47): every user has a display name of at least 3 characters - required when a user is created, cannot be
removed, trimmed, enforced by the database; existing users without one get their username. (#46, #50: the name is
returned for the top bar; the roles are still returned for the My account page.)"""
import sqlite3

import pytest
from sqlalchemy import text

from conftest import ADMIN, PASSWORD, Api

REQUIRED = "Display name is required."
TOO_SHORT = "Display name must be at least 3 characters."


def _new(env, username, **extra):
    body = {"first_name": "Test", "last_name": "Person", "username": username, "email": f"{username}@example.com",
            "password": PASSWORD,
            "security_domain": "FINANCIAL", "roles": ["BUDGET_USER"]}
    body.update(extra)
    return env.admin.post("/api/users", body)


def _error(r):
    assert r.status_code == 422, r.text
    e = r.json()["error"]
    assert e["errors"] == [{"field": "display_name", "message": e["message"]}]
    return e["message"]


@pytest.mark.parametrize("value", [None, "", "   ", "\t \n"])
def test_create_without_a_display_name_is_refused(env, value):
    r = _new(env, "nobody") if value is None else _new(env, "nobody", display_name=value)
    assert _error(r) == REQUIRED
    assert "nobody" not in [u["username"] for u in env.admin.get("/api/users").json()]


@pytest.mark.parametrize("value", ["a", "ab", "  ab  ", " a "])
def test_create_with_fewer_than_three_characters_after_trimming_is_refused(env, value):
    assert _error(_new(env, "shorty", display_name=value)) == TOO_SHORT
    assert "shorty" not in [u["username"] for u in env.admin.get("/api/users").json()]


def test_create_stores_the_trimmed_display_name(env):
    r = _new(env, "pat", display_name="   Pat Morgan  ")
    assert r.status_code == 201 and r.json()["display_name"] == "Pat Morgan"
    assert _new(env, "abc", display_name="Abc").json()["display_name"] == "Abc"            # exactly 3
    assert _new(env, "long", display_name="x" * 120).status_code == 201                     # the maximum is unchanged
    assert _new(env, "toolong", display_name="x" * 121).status_code == 422
    ev = env.auditor.get("/api/audit-events?object_type=user&sort=id&direction=desc").json()["items"]
    assert [e["after"]["display_name"] for e in ev if e["action"] == "USER_CREATED" and e["after"]["username"] == "pat"] == ["Pat Morgan"]


def test_edit_cannot_remove_or_shorten_the_display_name(env):
    uid = _new(env, "pat", display_name="Pat Morgan").json()["id"]
    for value in (None, "", "    "):
        assert _error(env.admin.patch(f"/api/users/{uid}", {"display_name": value})) == REQUIRED
    for value in ("P", "Pa", "  Pa "):
        assert _error(env.admin.patch(f"/api/users/{uid}", {"display_name": value})) == TOO_SHORT
    assert {u["id"]: u for u in env.admin.get("/api/users").json()}[uid]["display_name"] == "Pat Morgan"


def test_edit_accepts_a_valid_display_name_and_leaves_it_alone_when_not_sent(env):
    uid = _new(env, "pat", display_name="Pat Morgan").json()["id"]
    r = env.admin.patch(f"/api/users/{uid}", {"display_name": "  Patricia M.  "})
    assert r.status_code == 200 and r.json()["display_name"] == "Patricia M."
    r = env.admin.patch(f"/api/users/{uid}", {"email": "pm@example.com"})        # display_name not part of the request
    assert r.status_code == 200 and r.json()["display_name"] == "Patricia M." and r.json()["email"] == "pm@example.com"


def test_only_an_administrator_can_set_it(env):
    assert env.bm.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "zzz", "email": "z@z.org", "password": PASSWORD, "display_name": "Zed",
                                      "security_domain": "FINANCIAL", "roles": ["BUDGET_USER"]}).status_code == 403
    assert env.auditor.patch("/api/users/1", {"display_name": "Changed"}).status_code == 403


def test_first_administrator_gets_the_username_and_sign_in_returns_the_display_name(env):
    me = env.admin.get("/api/auth/me").json()
    assert me["display_name"] == ADMIN["admin_username"] == me["username"]
    a = Api(env.app)
    r = a.login("budgetmgr")
    assert r.json()["display_name"] == "Budgetmgr Person" and r.json()["username"] == "budgetmgr"
    assert r.json()["roles"] == ["BUDGET_MANAGER"]            # #50: still returned - shown on My account


def test_the_database_itself_refuses_a_user_without_a_display_name(env, app):
    with app.state.session_factory() as db:
        for value in (None, "", "  ", "ab", " ab "):
            with pytest.raises(Exception, match="display name"):
                db.execute(text("update app_user set display_name = :v where id = 1"), {"v": value})
            db.rollback()
        with pytest.raises(Exception, match="display name"):
            db.execute(text("insert into app_user (workspace_id, username, username_normalized, email, password_hash, active,"
                            " security_domain, theme, nav_collapsed, created_at, updated_at) select workspace_id, 'ghost',"
                            " 'ghost', email, password_hash, 1, security_domain, theme, 0, created_at, updated_at"
                            " from app_user where id = 1"))
        db.rollback()
        db.execute(text("update app_user set display_name = 'Fine Name' where id = 1"))      # a valid value passes
        db.commit()


def test_migration_gives_users_without_a_display_name_their_username(tmp_path):
    from alembic import command

    from fmpoc.db import alembic_config
    url = f"sqlite:///{tmp_path / 'm.sqlite3'}"
    command.upgrade(alembic_config(url), "0016_entity_phone_format")
    c = sqlite3.connect(tmp_path / "m.sqlite3")
    c.execute("pragma foreign_keys=off")
    cols = [r[1] for r in c.execute("pragma table_info(app_user)")]
    users = {1: ("admin", None), 2: ("treasurer", ""), 3: ("bookkeeper", "   "), 4: ("auditor", "Al"),
             5: ("pat", " Jo "), 6: ("kept1", "Pat Morgan"), 7: ("kept2", "Abc"), 8: ("kept3", "  Spaced Out  ")}
    for i, (username, shown) in users.items():
        row = {k: None for k in cols}
        row.update(id=i, workspace_id=1, username=username, username_normalized=username, email=f"{username}@example.com",
                   display_name=shown, password_hash="x", active=1, security_domain="FINANCIAL", theme="light",
                   nav_collapsed=0, created_at="2026-01-01 00:00:00", updated_at="2026-01-01 00:00:00")
        c.execute(f"insert into app_user ({','.join(row)}) values ({','.join('?' * len(row))})", list(row.values()))
    c.commit(); c.close()
    command.upgrade(alembic_config(url), "head")
    c = sqlite3.connect(tmp_path / "m.sqlite3")
    got = dict(c.execute("select id, display_name from app_user").fetchall())
    assert got == {1: "admin", 2: "treasurer", 3: "bookkeeper", 4: "auditor", 5: "pat",        # username copied
                   6: "Pat Morgan", 7: "Abc", 8: "  Spaced Out  "}                             # left exactly as they were
    assert c.execute("select count(*) from app_user").fetchone()[0] == 8
    command.upgrade(alembic_config(url), "head")                                               # running it again changes nothing
    assert dict(sqlite3.connect(tmp_path / "m.sqlite3").execute("select id, display_name from app_user").fetchall()) == got


def test_the_triggers_exist_at_head(tmp_path):
    """A later migration that rebuilds app_user (batch_alter_table) would silently drop them."""
    from fmpoc.db import upgrade_database
    url = f"sqlite:///{tmp_path / 'm.sqlite3'}"
    upgrade_database(url)
    names = {r[0] for r in sqlite3.connect(tmp_path / "m.sqlite3").execute(
        "select name from sqlite_master where type = 'trigger' and tbl_name = 'app_user'")}
    assert names == {"app_user_display_name_insert", "app_user_display_name_update"}
