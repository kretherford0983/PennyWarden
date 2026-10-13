"""2.0.0 build 7 (#125): reinitialize (keeping users) with an automatic safety backup."""
from __future__ import annotations

import json

import pytest

from conftest import PASSWORD, PDF_BYTES, Api
from test_v141_backup import _wait

from fmpoc import cli_restore
from fmpoc.app import create_app
from fmpoc.config import load_settings
from fmpoc.services import reinitialize as reinit
from fmpoc.services import server_recovery

OK = {"confirm": "reinitialize", "password": PASSWORD}


@pytest.fixture
def data(env, base):
    acct = base["acct"]["id"]
    t = env.txn(acct, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "12.34"}])
    r = env.ru.c.post(f"/api/attachments?owner_type=transaction&owner_id={t['id']}",
                      files={"file": ("receipt.pdf", PDF_BYTES)}, headers={"X-CSRF-Token": env.ru.csrf})
    assert r.status_code == 201
    ent = env.entity("Sample Supply Company, Inc")
    env.admin.put("/api/system/modules", {"checks": True})
    style = env.admin.post("/api/checks/styles", {"preset_key": "STANDARD_3UP"})
    assert style.status_code == 201
    env.ru.put("/api/me/preferences", {"theme": "dark"})
    return {"txn": t, "entity": ent}


def start(env, **body):
    r = env.admin.post("/api/system/reinitialize", {**OK, **body})
    assert r.status_code == 202, r.text
    return _wait(env.admin, f"/api/system/reinitialize/jobs/{r.json()['id']}")


def test_confirmation_is_checked_before_anything(env, data):
    pre = env.settings.data_dir / reinit.PRE_DIR
    for body, code in (({**OK, "confirm": "yes"}, 422), ({**OK, "password": "wrong-password-1"}, 400),
                       ({**OK, "passphrase": "short", "passphrase_confirmation": "short"}, 422),
                       ({**OK, "passphrase": "a long passphrase 1", "passphrase_confirmation": "other one 12345"}, 422)):
        assert env.admin.post("/api/system/reinitialize", body).status_code == code
    assert not pre.exists()
    assert env.ru.get(f"/api/transactions/{data['txn']['id']}").status_code == 200
    for c in (env.ru, env.bm, env.auditor, env.bu):
        assert c.post("/api/system/reinitialize", OK).status_code == 403
        assert c.get("/api/system/reinitialize").status_code == 403
    assert env.admin.c.post("/api/system/reinitialize", json=OK).status_code == 403    # CSRF


def test_reinitialize_removes_financial_data_keeps_users(env, data):
    info = env.admin.get("/api/system/reinitialize").json()
    assert info["counts"]["transactions"] == 1 and info["cooldown_until"] is None
    next_number_before = env.bm.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "N1",
                                                       "confirmations": ["DUPLICATE_ENTITY"]}).json()["entity_number"]
    j = start(env)
    assert j["state"] == "done", j
    res = j["result"]
    assert res["filename"].startswith("pre-reinitialize-") and "--use-server-key" in res["restore_command"]
    # other users were signed out; the Administrator stays
    assert env.ru.get("/api/auth/me").status_code == 401
    assert env.admin.get("/api/auth/me").status_code == 200
    ru = Api(env.app)
    assert ru.login("reguser").status_code == 200                         # users and passwords kept
    me = ru.get("/api/auth/me").json()
    assert me["theme"] == "dark"                                           # preferences kept
    bm = Api(env.app)
    bm.login("budgetmgr")
    assert bm.get("/api/fiscal-years").json() == []
    assert ru.get("/api/bank-accounts").json() == []
    assert ru.get(f"/api/transactions/{data['txn']['id']}").status_code == 404
    assert bm.get(f"/api/entities/{data['entity']['id']}").status_code == 404
    assert not any(p.is_file() for p in env.settings.attachments_dir.rglob("*"))
    assert env.admin.get("/api/system/status").json()["initialized"] is True   # no wizard
    assert env.admin.get("/api/system/status").json()["workspace_name"] == "Acme Org"
    assert env.admin.get("/api/system/modules").json()["checks"] is True        # module switches kept
    assert env.admin.get("/api/checks/setup").json()["styles"] == []             # Payments data removed
    # the Multiple entity is there; new entities and Fiscal Years can be created; numbers continue
    new = bm.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "After",
                                    "confirmations": ["DUPLICATE_ENTITY"]})
    assert new.status_code == 201 and new.json()["entity_number"] > next_number_before
    # the audit log is kept and has the event
    ev = env.admin.get("/api/audit-events?action=REINITIALIZE").json()["items"][0]
    assert ev["after"]["safety_backup"] == res["filename"] and ev["before"]["counts"]["transactions"] == 1
    assert env.admin.get("/api/audit-events?action=SYSTEM_INITIALIZED").json()["items"]
    # the safety backup is recoverable by the server and verified
    pre = env.settings.data_dir / reinit.PRE_DIR / res["filename"]
    assert pre.is_file() and server_recovery.passphrase_for(env.settings, pre)
    row = [r for r in env.admin.get("/api/system/server-backups").json()["backups"] if r["kind"] == "PRE_REINITIALIZE"]
    assert row and env.admin.post(f"/api/system/server-backups/{row[0]['id']}/remove-recovery", {}).status_code == 409
    # no passphrase anywhere in the audit log
    assert server_recovery.passphrase_for(env.settings, pre) not in json.dumps(
        env.admin.get("/api/audit-events?page_size=200").json())


def test_banner_until_an_administrator_acknowledges(env, data):
    start(env)
    ru = Api(env.app)
    ru.login("reguser")
    b = ru.get("/api/system/reinitialized").json()
    assert b["show"] and b["by"] == "admin" and b["can_acknowledge"] is False
    assert ru.post("/api/system/reinitialized/acknowledge", {}).status_code == 403
    aud = Api(env.app)
    aud.login("auditor")
    assert aud.get("/api/system/reinitialized").json()["show"]
    assert env.admin.post("/api/system/reinitialized/acknowledge", {}).json()["show"] is False   # the same admin may
    assert ru.get("/api/system/reinitialized").json()["show"] is False


def test_cooldown_web_but_not_cli(env, data, monkeypatch):
    start(env)
    r = env.admin.post("/api/system/reinitialize", OK)
    assert r.status_code == 409 and r.json()["error"]["code"] == "COOLDOWN"
    monkeypatch.setattr(cli_restore, "in_container", lambda: False)
    monkeypatch.setattr(cli_restore, "service_installed", lambda: False)
    monkeypatch.setattr(cli_restore, "app_answering", lambda _s: False)
    assert cli_restore.reinit_main(["--data-dir", str(env.settings.data_dir), "--yes"]) == 0
    # both safety backups exist
    assert len(list((env.settings.data_dir / reinit.PRE_DIR).glob("*.fmbak"))) == 2
    app2 = create_app(load_settings({"data_dir": str(env.settings.data_dir)}))
    a = Api(app2)
    a.login("admin")
    evs = a.get("/api/audit-events?action=REINITIALIZE").json()["items"]
    assert {e["after"]["via"] for e in evs} == {"system_about", "host_cli"}


def test_failed_safety_backup_removes_nothing(env, data, monkeypatch):
    from fmpoc.services import backup as bk

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(bk, "create_backup", boom)
    j = start(env)
    assert j["state"] == "failed" and "nothing was removed" in j["error"]
    assert env.ru.get(f"/api/transactions/{data['txn']['id']}").status_code == 200


def test_failed_wipe_rolls_back(env, data, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(reinit, "remove_attachment_files", lambda s: None)
    real = reinit.wipe

    def half(db, ws_id, ctx, *a, **k):
        real(db, ws_id, ctx, *a, **k)
        raise RuntimeError("after the deletes")
    monkeypatch.setattr(reinit, "wipe", half)
    j = start(env)
    assert j["state"] == "failed"
    assert env.ru.get(f"/api/transactions/{data['txn']['id']}").status_code == 200
    assert env.bm.get("/api/fiscal-years").json()


def test_cli_restore_of_the_safety_backup_brings_everything_back(env, data, monkeypatch):
    res = start(env)["result"]
    monkeypatch.setattr(cli_restore, "in_container", lambda: False)
    monkeypatch.setattr(cli_restore, "service_installed", lambda: False)
    monkeypatch.setattr(cli_restore, "app_answering", lambda _s: False)
    pre = env.settings.data_dir / reinit.PRE_DIR / res["filename"]
    assert cli_restore.main([str(pre), "--use-server-key", "--data-dir", str(env.settings.data_dir), "--yes"]) == 0
    app2 = create_app(load_settings({"data_dir": str(env.settings.data_dir)}))
    ru = Api(app2)
    ru.login("reguser")
    assert ru.get(f"/api/transactions/{data['txn']['id']}").status_code == 200


def test_mfa_code_required_when_enabled(env, data, monkeypatch):
    from fmpoc.services import mfa
    monkeypatch.setattr(mfa, "enabled", lambda db, user: True)
    monkeypatch.setattr(mfa, "verify", lambda db, km, user, code: "totp" if code == "123456" else None)
    r = env.admin.post("/api/system/reinitialize", OK)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INCORRECT_CODE"
    assert env.admin.post("/api/system/reinitialize", {**OK, "code": "000000"}).status_code == 400
    assert env.admin.get("/api/system/reinitialize").json()["code_required"] is True
    r = env.admin.post("/api/system/reinitialize", {**OK, "code": "123456"})
    assert r.status_code == 202
    assert _wait(env.admin, f"/api/system/reinitialize/jobs/{r.json()['id']}")["state"] == "done"
