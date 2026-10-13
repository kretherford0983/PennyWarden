"""2.0.0 build 7 (#130): maintenance mode."""
from __future__ import annotations

import datetime as dt

from fmpoc import config
from fmpoc.app import create_app


def on(client, message="Year-end close tonight.", starts_at=None):
    body = {"on": True, "message": message}
    if starts_at:
        body["starts_at"] = starts_at
    return client.put("/api/system/maintenance", body)


def test_on_blocks_changes_for_everyone_but_administrators(env, base):
    r = on(env.admin)
    assert r.status_code == 200 and r.json()["active"] is True
    # reading still works
    assert env.ru.get("/api/register?bank_account_id=%d" % base["acct"]["id"]).status_code == 200
    assert env.bm.get("/api/fiscal-years").status_code == 200
    # changes are refused, with the message
    r = env.ru.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "WITHDRAWAL",
                                          "transaction_date": "2026-08-01",
                                          "allocations": [{"budget_id": base["exp_leaf"], "amount": "1.00"}]})
    assert r.status_code == 503 and r.json()["error"]["code"] == "MAINTENANCE"
    assert "Year-end close tonight." in r.json()["error"]["message"]
    assert env.bm.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "X",
                                         "confirmations": ["DUPLICATE_ENTITY"]}).status_code == 503
    # nothing was written
    reg = env.ru.get("/api/register?bank_account_id=%d" % base["acct"]["id"]).json()
    assert not any(t.get("total") == "1.00" for t in reg.get("items", []))
    # preferences and signing out stay open; Administrators keep working
    assert env.ru.put("/api/me/preferences", {"theme": "dark"}).status_code == 200
    assert env.admin.put("/api/system/organization", {"name": "Acme Org Two"}).status_code == 200
    # the status (sign-in page) shows it
    st = env.ru.get("/api/system/status").json()
    assert st["maintenance_mode"]["active"] and st["maintenance_mode"]["message"] == "Year-end close tonight."
    # off: changes work again; audited
    r = env.admin.put("/api/system/maintenance", {"on": False})
    assert r.status_code == 200 and r.json()["on"] is False
    assert env.bm.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "X",
                                         "confirmations": ["DUPLICATE_ENTITY"]}).status_code == 201
    acts = [e["action"] for e in env.admin.get("/api/audit-events?page_size=50").json()["items"]]
    assert "MAINTENANCE_MODE_ON" in acts and "MAINTENANCE_MODE_OFF" in acts


def test_scheduled_start(env, base):
    later = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)).isoformat()
    r = on(env.admin, "Upgrade at 9 pm.", later)
    assert r.status_code == 200 and r.json()["scheduled"] is True and r.json()["active"] is False
    st = env.ru.get("/api/system/status").json()["maintenance_mode"]
    assert st["scheduled"] and st["message"] == "Upgrade at 9 pm." and st["starts_at"]
    # not active yet: changes still work
    assert env.bm.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Y",
                                         "confirmations": ["DUPLICATE_ENTITY"]}).status_code == 201
    # once the start has passed, it is active
    from fmpoc.models import Workspace
    with env.app.state.session_factory() as db:
        ws = db.query(Workspace).one()
        ws.maintenance_starts_at = dt.datetime.utcnow() - dt.timedelta(minutes=1)
        db.commit()
    assert env.bm.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Z",
                                         "confirmations": ["DUPLICATE_ENTITY"]}).status_code == 503
    too_far = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=90)).isoformat()
    assert on(env.admin, "x", too_far).status_code == 422


def test_validation_roles_and_text(env):
    assert on(env.admin, "").status_code == 422
    assert on(env.admin, "x" * 501).status_code == 422
    assert on(env.admin, "bad\x07").status_code == 422
    r = on(env.admin, "<script>alert(1)</script>")      # stored as text; React renders it inert
    assert r.status_code == 200 and r.json()["message"] == "<script>alert(1)</script>"
    env.admin.put("/api/system/maintenance", {"on": False})
    for c in (env.auditor, env.ru, env.bm, env.bu):
        assert on(c).status_code == 403
        assert c.put("/api/system/maintenance", {"on": False}).status_code == 403
        assert c.get("/api/system/maintenance").status_code == 403


def test_survives_a_restart(env, settings):
    on(env.admin, "Back soon.")
    app2 = create_app(config.load_settings({"data_dir": str(settings.data_dir)}))
    from fastapi.testclient import TestClient
    with TestClient(app2) as c:
        st = c.get("/api/system/status").json()
    assert st["maintenance_mode"]["active"] and st["maintenance_mode"]["message"] == "Back soon."
