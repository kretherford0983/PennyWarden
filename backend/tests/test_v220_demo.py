"""2.2.0 (#243): the downloadable demo - a backup carrying the demo marker, restored on a new local install; local
loopback only; reset to its pristine copy on every start and by Reset demo data (also from the sign-in page); Remove
the demo leaves nothing behind and the Initialization Wizard comes next; the marker can't be set from the web or API."""
from __future__ import annotations

import sqlite3
import time

import pytest

from conftest import PASSWORD, Api
from test_v141_backup import _backup, _restore

from fmpoc.app import create_app
from fmpoc.config import load_settings
from fmpoc.services import demo as demo_svc


def _mark(env) -> None:
    con = sqlite3.connect(env.settings.database_path)
    con.execute("UPDATE workspace SET demo_mode = 1")
    con.commit()
    con.close()


@pytest.fixture
def demo_blob(env, base):
    env.entity("Demo Vendor")
    _mark(env)
    return _backup(env)


def _fresh(tmp_path, name="evaluator", **kw):
    return create_app(load_settings({"data_dir": str(tmp_path / name), **kw}))


def _anon(app) -> Api:
    a = Api(app)
    a.pre_csrf()
    return a


def _install_demo(tmp_path, blob, name="evaluator"):
    app = _fresh(tmp_path, name)
    j = _restore(_anon(app), blob)
    assert j["state"] == "done", j
    return app


def _wait_ready(app) -> None:
    for _ in range(200):
        if app.state.maintenance is None:
            return
        time.sleep(0.05)
    raise AssertionError("still paused")


def test_install_reset_on_start_and_reset_button(env, demo_blob, tmp_path):
    app = _install_demo(tmp_path, demo_blob)
    st = Api(app).get("/api/system/status").json()
    assert st["demo"] is True and st["initialized"] is True
    assert (app.state.settings.data_dir / demo_svc.PRISTINE / "database" / "fmpoc.sqlite3").is_file()
    bm = Api(app)
    assert bm.login("budgetmgr").status_code == 200
    r = bm.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Typed By The Evaluator",
                                  "confirmations": ["DUPLICATE_ENTITY"]})
    assert r.status_code == 201
    eid = r.json()["id"]
    # a restart puts the pristine demo back
    app2 = create_app(load_settings({"data_dir": str(app.state.settings.data_dir)}))
    bm2 = Api(app2)
    assert bm2.login("budgetmgr").status_code == 200
    assert bm2.get(f"/api/entities/{eid}").status_code == 404
    # Reset demo data from the sign-in page (no session), after someone changed a password
    r = bm2.post("/api/auth/change-password", {"current_password": PASSWORD, "new_password": "Evaluator-Pass-1",
                                               "new_password_confirmation": "Evaluator-Pass-1"})
    assert r.status_code == 200
    r = _anon(app2).post("/api/system/demo/reset")
    assert r.status_code == 200, r.text
    _wait_ready(app2)
    assert Api(app2).login("budgetmgr").status_code == 200       # the published password again
    assert Api(app2).post("/api/system/demo/reset").status_code == 403   # still needs the sign-in page's token


def test_local_loopback_only(env, demo_blob, tmp_path):
    app = _install_demo(tmp_path, demo_blob)
    d = str(app.state.settings.data_dir)
    with pytest.raises(demo_svc.DemoError, match="runs only on this computer"):
        create_app(load_settings({"data_dir": d, "mode": "server"}))
    with pytest.raises(demo_svc.DemoError):
        create_app(load_settings({"data_dir": d, "host": "0.0.0.0"}))
    # a server refuses to restore the demo (nothing changes)
    srv = _fresh(tmp_path, "server", mode="server")
    j = _restore(_anon(srv), demo_blob)
    assert j["state"] == "failed" and "runs only on this computer" in j["error"] and "nothing was changed" in j["error"]


def test_remove_the_demo(env, demo_blob, tmp_path):
    app = _install_demo(tmp_path, demo_blob)
    data = app.state.settings.data_dir
    key_before = (data / "secrets").read_bytes() if (data / "secrets").is_file() else \
        sorted(p.read_bytes() for p in (data / "secrets").iterdir())
    (data / "config.toml").write_text("[server]\nlog_level = \"INFO\"\n", encoding="utf-8")
    bu = Api(app)
    bu.login("budgetuser")
    assert bu.post("/api/system/demo/remove", {"confirm": "REMOVE"}).status_code == 403    # the Administrator only
    adm = Api(app)
    adm.login("admin")
    assert adm.post("/api/system/demo/remove", {"confirm": "yes"}).status_code == 422
    assert adm.post("/api/system/demo/remove", {"confirm": "REMOVE"}).status_code == 200
    _wait_ready(app)
    st = Api(app).get("/api/system/status").json()
    assert st["initialized"] is False and st["demo"] is False
    assert not (data / demo_svc.PRISTINE).exists() and list((data / "attachments").iterdir()) == []
    assert list((data / "secrets").iterdir()) == [] and (data / "config.toml").is_file()
    assert _anon(app).post("/api/system/demo/reset").status_code == 404
    # the wizard makes a new key
    from conftest import ADMIN
    a = _anon(app)
    assert a.post("/api/system/initialize", ADMIN).status_code == 200
    assert sorted(p.read_bytes() for p in (data / "secrets").iterdir()) != key_before


def test_non_demo_restore_leaves_demo_mode(env, demo_blob, tmp_path):
    con = sqlite3.connect(env.settings.database_path)
    con.execute("UPDATE workspace SET demo_mode = 0")
    con.commit()
    con.close()
    real = _backup(env)
    app = _install_demo(tmp_path, demo_blob)
    adm = Api(app)
    adm.login("admin")
    j = _restore(adm, real, password=PASSWORD, confirm="RESTORE")      # over the demo: always whole, no choice
    assert j["state"] == "done", j
    assert app.state.demo is False and not (app.state.settings.data_dir / demo_svc.PRISTINE).exists()
    assert Api(app).get("/api/system/status").json()["demo"] is False


def test_the_marker_cant_be_set_through_the_api(env, base):
    adm = env.admin
    for url, body in (("/api/system/organization", {"name": "Acme Org", "demo_mode": True}),
                      ("/api/system/modules", {"fundraisers": True, "demo_mode": True})):
        r = adm.put(url, body)
        assert r.status_code == 422, (url, r.text)
    assert env.admin.post("/api/system/demo/reset").status_code == 404
    assert Api(env.app).get("/api/system/status").json()["demo"] is False
    con = sqlite3.connect(env.settings.database_path)
    assert con.execute("SELECT demo_mode FROM workspace").fetchone()[0] == 0
    con.close()


def test_no_scheduled_backups_or_update_check_in_the_demo(env, demo_blob, tmp_path):
    app = _install_demo(tmp_path, demo_blob)
    from fmpoc.services import scheduled_backup as sb
    from fmpoc.services import updates
    assert sb.tick(app) == [] and updates.check(app, force=True) is False


def test_cli_remove_demo(env, demo_blob, tmp_path, capsys):
    from fmpoc.__main__ import main
    from conftest import initialize
    plain = _fresh(tmp_path, "plain")
    initialize(plain)
    assert main(["remove-demo", "--data-dir", str(plain.state.settings.data_dir), "--yes"]) == 1   # not a demo
    assert "not the demo" in capsys.readouterr().out
    app = _install_demo(tmp_path, demo_blob)
    d = str(app.state.settings.data_dir)
    app.state.engine.dispose()
    assert main(["remove-demo", "--data-dir", d, "--yes"]) == 0
    assert "was removed" in capsys.readouterr().out
    app2 = create_app(load_settings({"data_dir": d}))
    assert Api(app2).get("/api/system/status").json()["initialized"] is False
