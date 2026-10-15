"""2.0.0 build 8 (#133): the readable audit log."""
from __future__ import annotations

import pathlib
import re

from fmpoc.services import audit_readable as ar


def events(client, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    r = client.get(f"/api/audit-events?{qs}")
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_every_action_code_has_a_readable_name():
    root = pathlib.Path(__file__).resolve().parents[1] / "fmpoc"
    codes = set()
    for p in root.rglob("*.py"):
        codes |= set(re.findall(r'audit\.record\(\s*\w+,\s*[\w()]+,\s*"([A-Z][A-Z0-9_]+)"', p.read_text(encoding="utf-8")))
        codes |= set(re.findall(r'"([A-Z][A-Z0-9_]+_(?:CREATED|UPDATED|DELETED|CHANGED|DISABLED|ENABLED|SET|REMOVED|'
                                r'DENIED|FAILED|ACTIVATED|DEACTIVATED|CLEARED|RESET|ON|OFF))"', p.read_text(encoding="utf-8")))
    assert len(codes) > 100
    for c in codes:
        label = ar.action_label(c)
        assert label and label != c and "_" not in label, c
    for c in ar.ACTION_LABELS:   # explicit labels belong to real codes
        assert c in codes or c in ("LOGIN_PASSWORD_ACCEPTED",), c


def test_unknown_action_and_fields_fall_back():
    assert ar.action_label("SOMETHING_NEW_HAPPENED") == "Something new happened"
    assert ar.field_label("manual_current_balance_cents") == "Current balance"
    assert ar.field_label("strange_new_field") == "Strange new field"
    assert ar.fmt("x_cents", 319930) == "$3,199.30" and ar.fmt("x_cents", -5) == "-$0.05"
    assert ar.fmt("active", True) == "Yes" and ar.fmt("status", "ACTIVE") == "Active"
    assert ar.fmt("check_number", "ABC") == "ABC" and ar.fmt("notes", "<script>x</script>") == "<script>x</script>"


def test_update_shows_only_changed_fields_and_raw_json_is_unchanged(env, base):
    acct = base["acct"]["id"]
    r = env.bm.patch(f"/api/bank-accounts/{acct}", {"account_name": "Main Checking"})
    assert r.status_code == 200, r.text
    ev = events(env.auditor, action="BANK_ACCOUNT_UPDATED")[0]
    rd = ev["readable"]
    assert rd["kind"] == "update" and "Bank account updated" in rd["summary"] and '"Main Checking"' in rd["summary"]
    ch = {c["field"]: c for c in rd["changes"]}
    assert set(ch) == {k for k in set(ev["before"]) | set(ev["after"]) if ev["before"].get(k) != ev["after"].get(k)}
    assert ch["account_name"]["changed"] is True and ch["account_name"]["after"] == "Main Checking"
    assert ch["account_name"]["label"] == "Account name"
    # the raw snapshots are still there, as stored
    assert ev["after"]["account_name"] == "Main Checking"


def test_create_with_lines_sub_table_currency_and_related_names(env, base):
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [
        {"budget_id": base["exp_leaf"], "amount": "12.50", "invoice_number": "A1"},
        {"budget_id": base["exp_leaf"], "amount": "7.25", "invoice_number": "A2"}])
    ev = [e for e in events(env.auditor, action="TRANSACTION_CREATED") if e["object_id"] == str(t["id"])][0]
    rd = ev["readable"]
    assert rd["kind"] == "create"
    tables = [c for c in rd["changes"] if c.get("after_table")]
    assert tables, rd["changes"]
    tbl = tables[0]["after_table"]
    flat = " ".join(str(x) for row in tbl["rows"] for x in row)
    assert "$12.50" in flat and "$7.25" in flat and "Other (2027)" in flat and "(#" in flat
    text = str(rd)
    assert "98765432" not in text                                     # never more than the snapshot holds


def test_names_recorded_at_the_time_and_missing_records(env, base):
    ent = env.entity("Sample Supply Company")
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "1.00"}],
                entity_id=ent["id"])
    r = env.ru.patch(f"/api/entities/{ent['id']}", {"organization_name": "Renamed Supply Company"})
    assert r.status_code == 200, r.text
    ev = [e for e in events(env.auditor, action="TRANSACTION_CREATED") if e["object_id"] == str(t["id"])][0]
    assert "Sample Supply Company" in str(ev["readable"]) and "Renamed Supply" not in str(ev["readable"])
    # an older event without stored labels whose record is gone
    from types import SimpleNamespace
    with env.app.state.session_factory() as db:
        fake = SimpleNamespace(actor_name=None, actor_username="old", correlation_id=None, action="TRANSACTION_UPDATED",
                               object_type="register_transaction", object_id="1", labels=None,
                               before_snapshot={"budget_id": 999999}, after_snapshot={"budget_id": 999998})
        rd = ar.readable(db, fake, False, True)
    assert "#999998 (no longer exists)" in str(rd)


def test_administrators_see_no_financial_content(env, base):
    env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "55.00"}])
    for ev in events(env.admin, object_type="register_transaction"):
        assert ev["before"] is None and ev["after"] is None and ev["snapshots_withheld"]
        rd = ev["readable"]
        assert rd["kind"] == "withheld" and rd["changes"] == []
        assert "55" not in rd["summary"] and "Donations" not in rd["summary"]
    # a user event: the full readable view
    ev = events(env.admin, action="USER_CREATED")[0]
    assert ev["readable"]["changes"] and ev["readable"]["kind"] == "create"
    # non-financial events that reference financial records don't name them for Administrators
    from types import SimpleNamespace
    with env.app.state.session_factory() as db:
        fake = SimpleNamespace(actor_name=None, actor_username="x", correlation_id=None, action="CHECK_ACCOUNT_SETTINGS",
                               object_type="check_style", object_id="1", labels={"bank_account:1": "Secret Name (****1234)"},
                               before_snapshot=None, after_snapshot={"bank_account_id": 1})
        rd = ar.readable(db, fake, False, False)
    assert "Secret Name" not in str(rd) and "#1" in str(rd)


def test_filter_meta_has_readable_names(env):
    m = env.admin.get("/api/audit-events/meta").json()
    labels = {a["code"]: a["label"] for a in m["actions"]}
    assert labels["USER_CREATED"] == "User created" and labels["LOGIN"] == "Signed in"
    assert {"code": "user", "label": "User"} in m["object_types"]
    assert env.ru.get("/api/audit-events/meta").status_code == 403
    # filtering still uses the codes
    assert all(e["action"] == "USER_CREATED" for e in events(env.admin, action="USER_CREATED"))


def test_cli_events_show_command_line(env):
    from types import SimpleNamespace
    with env.app.state.session_factory() as db:
        fake = SimpleNamespace(actor_name=None, actor_username=None, correlation_id="host-cli", action="MFA_RESET",
                               object_type="user", object_id="2", labels=None, before_snapshot=None,
                               after_snapshot={"via": "host_cli"})
        assert ar.readable(db, fake, False, True)["summary"].startswith("command line:")
