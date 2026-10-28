"""2.2.0 (#319): restore - choose what to restore (Data, Settings sections, Reminders, Users).

Decisions (Kyle, 2026-10-22/24): Data is never split; a partial restore keeps the current audit log and adds one
SYSTEM_RESTORED event listing what was restored; the backup's key is always installed and kept values are re-encrypted;
users missing from a backup are kept, inactivated and reported; records referring to users that aren't there are
listed before anything changes and those users are added from the backup (or Users are included); it never blocks."""
from __future__ import annotations

import json

import pytest

from conftest import PASSWORD, Api, initialize
from test_v141_backup import PASS, _backup, _restore, _wait
from test_v200_cli_restore import backup as cli_backup
from test_v200_cli_restore import host, run  # noqa: F401 (fixture)

from fmpoc.app import create_app
from fmpoc.config import load_settings
from fmpoc.services import partial_restore as pr

NEW_PW = "Changed-After-Backup-7"


def _restore_parts(client, blob, domains, **kw):
    return _restore(client, blob, password=PASSWORD, confirm="RESTORE", domains=domains, **kw)


def _login(app, user, pw=PASSWORD):
    c = Api(app)
    r = c.login(user, pw)
    assert r.status_code == 200, r.text
    return c


def test_names_and_choices():
    assert pr.parse_names("data, settings") == ["data", *pr.SETTINGS_SECTIONS]
    assert pr.parse_names("users,settings.payments") == ["settings.payments", "users"]
    assert pr.is_full(pr.parse_names("all"))
    with pytest.raises(pr.RestoreChoiceError, match="never split"):
        pr.parse_names("data.bank_accounts")
    with pytest.raises(pr.RestoreChoiceError, match="Unknown part"):
        pr.parse_names("everything")
    with pytest.raises(pr.RestoreChoiceError):
        pr.normalize([])


def test_the_restore_waits_for_the_choice(env, base):
    blob = _backup(env)
    j = _restore_parts(env.admin, blob, None)
    assert j["state"] == "choose" and j["step"] == "Waiting for what to restore"
    names = [d["name"] for d in j["result"]["domains"]]
    assert names == list(pr.DOMAINS) and j["result"]["same_key"] is True
    assert j["result"]["domains"][0]["counts"]["fiscal_years"] == 1
    assert "_event" not in json.dumps(j) and "_backup_db" not in json.dumps(j)
    jid = j["id"]
    # only the Administrator who started it; Data can't be split; a check changes nothing
    assert env.bm.post(f"/api/system/restore/jobs/{jid}/check", {"domains": ["data"]}).status_code == 403
    r = env.admin.post(f"/api/system/restore/jobs/{jid}/check", {"domains": ["data.budgets"]})
    assert r.status_code == 422 and "never split" in r.json()["error"]["message"]
    r = env.admin.post(f"/api/system/restore/jobs/{jid}/check", {"domains": ["data", "reminders"]})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["full"] is False and [x["name"] for x in c["restored"]] == ["data", "reminders"]
    assert "users" in [x["name"] for x in c["kept"]] and c["check"]["missing_users"] == []
    # another backup or restore can't start meanwhile
    r = env.admin.post("/api/system/backups", {"password": PASSWORD, "passphrase": PASS, "passphrase_confirmation": PASS})
    assert r.status_code == 409
    r = env.admin.post(f"/api/system/restore/jobs/{jid}/choose", {"domains": ["data"]})
    assert r.status_code == 200
    j = _wait(env.admin, f"/api/system/restore/jobs/{jid}")
    assert j["state"] == "done" and j["result"]["partial"] is True and j["result"]["restored"] == ["data"]
    assert env.admin.post(f"/api/system/restore/jobs/{jid}/choose", {"domains": ["data"]}).status_code in (401, 403, 409)


def test_data_only_keeps_users_settings_reminders_and_the_audit_log(env, base):
    """The test-baseline case: data back to the backup; users (with their new passwords), settings, reminders and
    the audit log as they are now."""
    acct = base["acct"]["id"]
    t1 = env.txn(acct, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "10.00"}])
    blob = _backup(env)
    # after the backup
    later = env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "25.50"}])
    late_entity = env.entity("Entered After Backup")
    assert env.bu.post("/api/auth/change-password", {"current_password": PASSWORD, "new_password": NEW_PW,
                                                      "new_password_confirmation": NEW_PW}).status_code == 200
    newbie = env.user("newbie", "FINANCIAL", ["REGISTER_USER"])
    assert env.admin.put("/api/system/backup-age", {"days": 3}).status_code == 200
    rem = env.bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "Pay rent", "due_date": "2030-01-01"})
    assert rem.status_code == 201, rem.text
    rem_linked = env.bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "Check account",
                                                "due_date": "2030-01-02", "link_type": "BANK_ACCOUNT",
                                                "link_id": acct})
    assert rem_linked.status_code == 201, rem_linked.text
    j = _restore_parts(env.admin, blob, ["data"])
    assert j["state"] == "done", j
    assert j["result"]["report_summary"] and "1 transaction" in j["result"]["report_summary"]
    ru = _login(env.app, "reguser")
    assert ru.get(f"/api/transactions/{later['id']}").status_code == 404           # data is the backup's
    assert ru.get(f"/api/transactions/{t1['id']}").status_code == 200
    assert ru.get(f"/api/entities/{late_entity['id']}").status_code == 404
    _login(env.app, "budgetuser", NEW_PW)                                          # users as they are now
    assert Api(env.app).login("budgetuser", PASSWORD).status_code != 200
    _login(env.app, "newbie")
    assert newbie
    bm = _login(env.app, "budgetmgr")
    titles = {r["title"]: r for r in bm.get("/api/reminders?view=upcoming").json()}
    assert "Pay rent" in titles                                                    # reminders kept
    assert titles["Check account"]["link"] is not None                            # its account is in the backup too
    adm = _login(env.app, "admin")
    assert adm.get("/api/system/backup-age").json()["warning_days"] == 3                   # settings kept
    # the audit log is the current one: it still has what happened after the backup, plus the restore
    assert adm.get("/api/audit-events?action=PASSWORD_CHANGED").json()["total"] >= 1
    ev = adm.get("/api/audit-events?action=SYSTEM_RESTORED").json()["items"][0]
    assert ev["after"]["partial"] is True and ev["after"]["restored"] == ["data"]
    assert "users" in ev["after"]["kept"] and ev["after"]["report"]
    assert adm.get("/api/audit-events?action=RESTORE_STARTED").json()["total"] == 1


def test_users_only_keeps_newer_users_inactivated_and_the_data(env, base):
    blob = _backup(env)
    late_entity = env.entity("Entered After Backup")
    env.user("newbie", "FINANCIAL", ["REGISTER_USER"])
    assert env.bu.post("/api/auth/change-password", {"current_password": PASSWORD, "new_password": NEW_PW,
                                                      "new_password_confirmation": NEW_PW}).status_code == 200
    j = _restore_parts(env.admin, blob, ["users"])
    assert j["state"] == "done", j
    assert any("newbie" in n and "inactivated" in n for n in j["result"]["notes"])
    assert j["result"]["report_summary"] is None                     # no re-entry report without Data
    _login(env.app, "budgetuser", PASSWORD)                          # the backup's password again
    assert Api(env.app).login("newbie").status_code != 200            # kept, inactivated
    adm = _login(env.app, "admin")
    users = {u["username"]: u for u in adm.get("/api/users").json()}
    assert users["newbie"]["active"] is False
    ru = _login(env.app, "reguser")
    assert ru.get(f"/api/entities/{late_entity['id']}").status_code == 200   # data kept


def test_settings_sections_and_the_organization_profile(env, base):
    adm = env.admin
    assert adm.put("/api/system/organization", {"name": "Acme Org", "city": "Springfield"}).status_code == 200
    assert adm.put("/api/system/backup-age", {"days": 5}).status_code == 200
    blob = _backup(env)
    assert adm.put("/api/system/organization", {"name": "Acme Org Inc", "city": "Shelbyville"}).status_code == 200
    assert adm.put("/api/system/backup-age", {"days": 9}).status_code == 200
    late_entity = env.entity("Entered After Backup")
    # General only: the profile and name come back, the Backups section and the data stay as they are
    j = _restore_parts(adm, blob, ["settings.general"])
    assert j["state"] == "done", j
    ru = _login(env.app, "reguser")
    assert ru.get(f"/api/entities/{late_entity['id']}").status_code == 200
    a2 = _login(env.app, "admin")
    org = a2.get("/api/system/organization").json()
    assert (org["name"], org["city"]) == ("Acme Org", "Springfield")
    assert a2.get("/api/system/backup-age").json()["warning_days"] == 9
    # Data without General: the organization entity comes back with the data, its profile stays the current one
    assert a2.put("/api/system/organization", {"name": "Acme Org", "city": "Capital City"}).status_code == 200
    j = _restore_parts(a2, blob, ["data"])
    assert j["state"] == "done", j
    a3 = _login(env.app, "admin")
    assert a3.get("/api/system/organization").json()["city"] == "Capital City"


def _second_install(tmp_path, name="new-host"):
    app2 = create_app(load_settings({"data_dir": str(tmp_path / name)}))
    a = initialize(app2)
    return app2, a


def test_move_to_a_new_host_settings_and_users_then_data(env, base, tmp_path):
    """The second use case: Settings and Users first, then Data from a later backup; a user added on the old server
    in between is listed before anything changes and added from the backup."""
    b1 = _backup(env)
    app2, a2 = _second_install(tmp_path)
    j = _restore(a2, b1, password=PASSWORD, confirm="RESTORE", domains=["settings", "users"])
    assert j["state"] == "done", j
    # on the old server: a new user enters data, then the switch backup
    late = env.user("lateuser", "FINANCIAL", ["REGISTER_USER"])
    ent = env.entity("By The Late User", client=late)
    b2 = _backup(env)
    a2 = _login(app2, "admin")
    j = _restore(a2, b2, password=PASSWORD, confirm="RESTORE", domains=None)
    jid = j["id"]
    c = a2.post(f"/api/system/restore/jobs/{jid}/check", {"domains": ["data", "reminders"]}).json()
    assert [u["username"] for u in c["check"]["missing_users"]] == ["lateuser"]
    assert a2.post(f"/api/system/restore/jobs/{jid}/choose", {"domains": ["data", "reminders"],
                                                               "missing_users": "add"}).status_code == 200
    j = _wait(a2, f"/api/system/restore/jobs/{jid}")
    assert j["state"] == "done", j
    assert any("lateuser" in n for n in j["result"]["notes"])
    lu = _login(app2, "lateuser")
    assert lu.get(f"/api/entities/{ent['id']}").status_code == 200


def test_another_installations_key_kept_values_re_encrypted(env, base, tmp_path):
    """Users only from another installation: the new host's bank account (kept Data) is re-encrypted with the
    backup's key and can still be revealed."""
    blob = _backup(env)
    app2, a2 = _second_install(tmp_path, "other")
    from conftest import Env
    e2 = Env.__new__(Env)
    e2.app, e2.settings, e2.admin = app2, app2.state.settings, a2
    e2.bm = e2.user("budgetmgr", "FINANCIAL", ["BUDGET_MANAGER"])
    acct = e2.account(number="5555000011112222")
    j = _restore(a2, blob, password=PASSWORD, confirm="RESTORE", domains=["users"])
    assert j["state"] == "done", j
    assert any("re-encrypted" in n for n in j["result"]["notes"])
    bm = _login(app2, "budgetmgr")
    r = bm.post(f"/api/bank-accounts/{acct['id']}/reveal", {"password": PASSWORD})
    assert r.status_code == 200 and "5555000011112222" in r.text
    # the new host now uses the backup's key
    import fmpoc.security.crypto as crypto
    assert crypto.load_key(app2.state.settings.secrets_dir).check_value == \
        crypto.load_key(env.settings.secrets_dir).check_value


def test_full_restore_is_unchanged(env, base):
    blob = _backup(env)
    env.user("newbie", "FINANCIAL", ["REGISTER_USER"])
    j = _restore_parts(env.admin, blob, ["all"])
    assert j["state"] == "done" and j["result"]["partial"] is False
    assert Api(env.app).login("newbie").status_code != 200            # replaced entirely, as before
    adm = _login(env.app, "admin")
    ev = adm.get("/api/audit-events?action=SYSTEM_RESTORED").json()["items"][0]
    assert ev["after"]["partial"] is False
    assert adm.get("/api/audit-events?action=RESTORE_STARTED").json()["total"] == 0   # the backup's log


def test_cli_only_skip_and_list(env, base, tmp_path, host, capsys):  # noqa: F811
    p, _ = cli_backup(env, tmp_path)
    late_entity = env.entity("Entered After Backup")
    env.user("newbie", "FINANCIAL", ["REGISTER_USER"])
    assert run(env, str(p), "--use-server-key", "--list") == 0
    out = capsys.readouterr().out
    assert "data" in out and "settings.payments" in out and "users" in out and "1 fiscal years" in out
    assert run(env, str(p), "--use-server-key", "--only", "data.budgets", "--yes") == 2
    assert run(env, str(p), "--use-server-key", "--skip", "data,reminders", "--yes") == 0
    out = capsys.readouterr().out
    assert "Keeping as is: data, reminders" in out and "newbie" in out
    app2 = create_app(load_settings({"data_dir": str(env.settings.data_dir)}))
    ru = _login(app2, "reguser")
    assert ru.get(f"/api/entities/{late_entity['id']}").status_code == 200
    adm = _login(app2, "admin")
    ev = adm.get("/api/audit-events?action=SYSTEM_RESTORED").json()["items"][0]
    assert ev["after"]["via"] == "host_cli" and ev["after"]["kept"] == ["data", "reminders"]
