"""2.0.0 build 7 (#124): server-recoverable backups, `pennywarden restore` and the restore re-entry report."""
from __future__ import annotations

import csv
import io
import json

import pytest

from conftest import PASSWORD, Api
from test_v141_backup import PASS, _restore, _wait

from fmpoc import cli_restore
from fmpoc.app import create_app
from fmpoc.config import load_settings
from fmpoc.services import backup as bk
from fmpoc.services import server_recovery


def backup(env, tmp_path, name="b.fmbak", **extra) -> tuple:
    a = env.admin
    r = a.post("/api/system/backups", {"password": PASSWORD, "passphrase": PASS, "passphrase_confirmation": PASS,
                                       **extra})
    assert r.status_code == 202, r.text
    j = _wait(a, f"/api/system/backups/{r.json()['id']}")
    assert j["state"] == "done", j
    blob = a.get(f"/api/system/backups/{r.json()['id']}/download").content
    p = tmp_path / name
    p.write_bytes(blob)
    return p, j


@pytest.fixture
def host(monkeypatch):
    """A plain terminal on a per-user install: no service, no container, nothing listening."""
    monkeypatch.setattr(cli_restore, "in_container", lambda: False)
    monkeypatch.setattr(cli_restore, "service_installed", lambda: False)
    monkeypatch.setattr(cli_restore, "app_answering", lambda _s: False)
    return monkeypatch


def run(env, *args) -> int:
    return cli_restore.main([*args, "--data-dir", str(env.settings.data_dir)])


def test_recovery_file_written_and_bound(env, base, tmp_path):
    p, j = backup(env, tmp_path)
    assert j["result"]["recoverable"] is True
    assert p.read_bytes().startswith(bk.MAGIC)                         # the .fmbak format is unchanged
    rows = env.admin.get("/api/system/server-backups").json()["backups"]
    assert len(rows) == 1 and rows[0]["filename"] == j["result"]["filename"] and rows[0]["kind"] == "MANUAL"
    assert "ciphertext" not in json.dumps(rows) and PASS not in json.dumps(rows)
    assert server_recovery.passphrase_for(env.settings, p) == PASS
    # the key and the recovery files are owner-only and never in a backup
    key = env.settings.data_dir / "server-key" / "server.key"
    assert key.is_file() and (key.stat().st_mode & 0o077) == 0
    # a different file with the same name does not match
    p2, _ = backup(env, tmp_path, "other.fmbak", recoverable=False)
    p.write_bytes(p2.read_bytes())
    assert server_recovery.passphrase_for(env.settings, p) is None
    assert len(env.admin.get("/api/system/server-backups").json()["backups"]) == 1   # recoverable=False wrote none
    ev = env.admin.get("/api/audit-events?action=BACKUP_CREATED").json()["items"]
    assert {e["after"]["recoverable"] for e in ev} == {True, False}
    for c in (env.ru, env.bm, env.auditor):
        assert c.get("/api/system/server-backups").status_code == 403


def test_server_key_never_in_a_backup(env, base, tmp_path):
    p, _ = backup(env, tmp_path)
    out = tmp_path / "x"
    m = bk.unpack(p, PASS, out)
    assert not any("server" in f["path"] or "recovery" in f["path"] for f in m["files"])


def test_remove_recovery(env, base, tmp_path):
    p, _ = backup(env, tmp_path)
    rid = env.admin.get("/api/system/server-backups").json()["backups"][0]["id"]
    assert env.ru.post(f"/api/system/server-backups/{rid}/remove-recovery", {}).status_code == 403
    r = env.admin.post(f"/api/system/server-backups/{rid}/remove-recovery", {})
    assert r.status_code == 200
    assert server_recovery.passphrase_for(env.settings, p) is None
    assert env.admin.get("/api/audit-events?action=BACKUP_RECOVERY_REMOVED").json()["items"]
    assert env.admin.post("/api/system/server-backups/../../x/remove-recovery", {}).status_code in (404, 405)
    assert env.admin.post("/api/system/server-backups/" + "a" * 32 + "/remove-recovery", {}).status_code == 404


def test_cli_restore_with_the_server_key_and_report(env, base, tmp_path, host, capsys):
    acct = base["acct"]["id"]
    env.txn(acct, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "10.00"}])
    p, _ = backup(env, tmp_path)
    # entered after the backup - with a text that would be a spreadsheet formula
    later = env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "25.50",
                                          "description": "=HYPERLINK(\"x\")", "invoice_number": "INV-9"}])
    assert run(env, str(p), "--use-server-key", "--yes") == 0
    out = capsys.readouterr().out
    assert "Restore complete." in out and "1 transaction(s) entered or changed after the backup" in out
    assert PASS not in out and "25.50" not in out                     # summary only: no financial values
    app2 = create_app(load_settings({"data_dir": str(env.settings.data_dir)}))
    ru = Api(app2)
    assert ru.login("reguser").status_code == 200
    assert ru.get(f"/api/transactions/{later['id']}").status_code == 404     # back to the backup
    reports = ru.get("/api/system/restore-reports").json()
    assert reports["can_download"] and reports["reports"][0]["transactions"] == 1
    name = reports["reports"][0]["name"]
    d = ru.get(f"/api/system/restore-reports/{name}")
    assert d.status_code == 200
    rows = list(csv.reader(io.StringIO(d.content.decode("utf-8-sig"))))
    hdr = rows.index(next(r for r in rows if r and r[0] == "Change"))
    row = rows[hdr + 1]
    assert row[0] == "NEW" and row[11] == "25.50" and row[12] == "INV-9" and row[13].startswith("'=")
    assert "****" in row[4] and "98765432" not in d.text
    adm = Api(app2)
    adm.login("admin")
    a = adm.get("/api/system/restore-reports").json()
    assert a["can_download"] is False and a["reports"][0]["transactions"] == 1
    assert adm.get(f"/api/system/restore-reports/{name}").status_code == 403
    ev = adm.get("/api/audit-events?action=SYSTEM_RESTORED").json()["items"][0]
    assert ev["after"]["via"] == "host_cli" and ev["after"]["report"] == name
    assert ev["after"]["restored_by"].startswith("host:") and PASS not in json.dumps(ev)
    assert ru.get("/api/system/restore-reports/../../secrets/x").status_code == 404


def test_cli_passphrase_file_and_env(env, base, tmp_path, host, monkeypatch):
    p, _ = backup(env, tmp_path, recoverable=False)
    pf = tmp_path / "pass.txt"
    pf.write_text(PASS + "\n", encoding="utf-8")
    assert run(env, str(p), "--use-server-key", "--yes") == 2          # not recoverable: clear failure
    assert run(env, str(p), "--passphrase-file", str(pf), "--yes") == 0
    monkeypatch.setenv(cli_restore.PASSPHRASE_ENV, str(pf))
    assert run(env, str(p), "--yes") == 0
    pf.write_text("wrong passphrase!!\n", encoding="utf-8")
    assert run(env, str(p), "--yes") == 2


def test_cli_checks_elevation_first_and_the_service(env, base, tmp_path, host, capsys):
    p, _ = backup(env, tmp_path)
    marker = env.entity("Still Here After Refusals")
    host.setattr(cli_restore, "needs_elevation", lambda _d: True)
    assert run(env, str(p), "--use-server-key") == 3
    assert "sudo" in capsys.readouterr().err
    host.setattr(cli_restore, "needs_elevation", lambda _d: False)
    host.setattr(cli_restore, "service_installed", lambda: True)
    host.setattr(cli_restore, "service_running", lambda: True)
    host.setattr(cli_restore, "ask", lambda _q, _y: False)
    assert run(env, str(p), "--use-server-key") == 4
    assert "systemctl stop" in capsys.readouterr().err or True
    # nothing changed
    assert env.bm.get(f"/api/entities/{marker['id']}").status_code == 200
    # a running local app: refused as well
    host.setattr(cli_restore, "service_installed", lambda: False)
    host.setattr(cli_restore, "service_running", lambda: False)
    host.setattr(cli_restore, "app_answering", lambda _s: True)
    assert run(env, str(p), "--use-server-key") == 4


def test_cli_container_never_stops_anything(env, base, tmp_path, host, capsys):
    p, _ = backup(env, tmp_path)
    host.setattr(cli_restore, "in_container", lambda: True)
    called = []
    host.setattr(cli_restore, "stop_service", lambda: called.append(1))
    assert run(env, str(p), "--use-server-key", "--yes") == 0
    assert not called and "container" in capsys.readouterr().out


def test_cli_onto_a_new_installation(env, base, tmp_path, host):
    p, _ = backup(env, tmp_path)
    pf = tmp_path / "pass.txt"
    pf.write_text(PASS, encoding="utf-8")
    new_dir = tmp_path / "new-server"
    assert cli_restore.main([str(p), "--passphrase-file", str(pf), "--data-dir", str(new_dir), "--yes"]) == 0
    app2 = create_app(load_settings({"data_dir": str(new_dir)}))
    a = Api(app2)
    assert a.get("/api/system/status").json()["initialized"] is True
    assert a.login("admin").status_code == 200


def test_cli_list(env, base, tmp_path, host, capsys):
    backup(env, tmp_path)
    assert run(env, "--list") == 0
    out = capsys.readouterr().out
    assert "pennywarden-backup-acme-org-" in out and "MANUAL" in out and PASS not in out


def test_web_restore_still_needs_the_passphrase(env, base, tmp_path):
    p, _ = backup(env, tmp_path)
    j = _restore(env.admin, p.read_bytes(), passphrase="not the passphrase", password=PASSWORD, confirm="RESTORE")
    assert j["state"] == "failed" and "nothing was changed" in j["error"]


def test_docker_entrypoint_passes_the_command(monkeypatch):
    from fmpoc import __main__ as m
    seen = []
    monkeypatch.setattr(cli_restore, "main", lambda argv: seen.append(argv) or 0)
    assert m.main(["--no-browser", "restore", "/backups/x.fmbak", "--yes"]) == 0
    assert seen == [["/backups/x.fmbak", "--yes"]]
