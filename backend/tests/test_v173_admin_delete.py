"""1.7.3 (#52, #53): Budget Admin deletes budgets of a Fiscal Year that is not approved; Register Admin deletes
uncleared transactions. Delete = status Deleted (BR-001: nothing is removed); Auditors still see the records."""
import sqlite3

import pytest

from conftest import PASSWORD


@pytest.fixture
def admins(env):
    ba = env.user("budgetadmin", "FINANCIAL", ["BUDGET_MANAGER", "BUDGET_ADMIN"])
    ra = env.user("regadmin", "FINANCIAL", ["REGISTER_USER", "REGISTER_ADMIN"])
    return {"ba": ba, "ra": ra}


def _new_user(env, username, roles):
    return env.admin.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": username, "email": f"{username}@example.com", "password": PASSWORD,
                                         "display_name": "Some Person", "security_domain": "FINANCIAL", "roles": roles})


# ------------------------------------------------------------------ roles
def test_admin_roles_need_their_base_role(env):
    r = _new_user(env, "xx1", ["BUDGET_ADMIN"])
    assert r.status_code == 422 and r.json()["error"]["message"] == "Budget Admin can only be given together with Budget Manager."
    r = _new_user(env, "xx2", ["REGISTER_ADMIN", "BUDGET_USER"])
    assert r.status_code == 422 and "Register Admin can only be given together with Register User" in r.text
    ok = _new_user(env, "xx3", ["BUDGET_MANAGER", "BUDGET_ADMIN"])
    assert ok.status_code == 201
    # removing the base role later is refused too
    r = env.admin.patch(f"/api/users/{ok.json()['id']}", {"roles": ["BUDGET_ADMIN", "BUDGET_USER"]})
    assert r.status_code == 422
    assert _new_user(env, "xx4", ["BUDGET_ADMIN", "AUDITOR"]).status_code == 422          # domains still exclusive


def test_roles_listed_and_permissions(env, admins):
    assert "budget.delete" in admins["ba"].get("/api/auth/me").json()["permissions"]
    assert "transaction.delete" in admins["ra"].get("/api/auth/me").json()["permissions"]
    assert "budget.delete" not in env.bm.get("/api/auth/me").json()["permissions"]
    assert "transaction.delete" not in env.ru.get("/api/auth/me").json()["permissions"]


def test_migration_adds_the_roles(tmp_path):
    from alembic import command

    from fmpoc.db import alembic_config
    url = f"sqlite:///{tmp_path / 'm.sqlite3'}"
    command.upgrade(alembic_config(url), "0018_bank_account_sort_order")
    c = sqlite3.connect(tmp_path / "m.sqlite3")
    for code, name, dom in [("ADMINISTRATOR", "Administrator", "ADMINISTRATOR"), ("BUDGET_MANAGER", "Budget Manager", "FINANCIAL")]:
        c.execute("insert into role (code, name, security_domain) values (?, ?, ?)", (code, name, dom))
    c.commit(); c.close()
    command.upgrade(alembic_config(url), "head")
    command.upgrade(alembic_config(url), "head")
    got = sorted(r[0] for r in sqlite3.connect(tmp_path / "m.sqlite3").execute("select code from role"))
    assert got == ["ADMINISTRATOR", "BUDGET_ADMIN", "BUDGET_MANAGER", "INVOICE_MANAGER", "REGISTER_ADMIN"]   # 2.4.0 (#251)
    cols = [r[1] for r in sqlite3.connect(tmp_path / "m.sqlite3").execute("pragma table_info(register_transaction)")]
    assert {"deleted_at", "deleted_by_user_id", "delete_reason"} <= set(cols)


# ------------------------------------------------------------------ #52 budgets
def _codes(client, fy):
    t = client.get(f"/api/budgets?fiscal_year_id={fy}").json()
    return [r["display_code"] for r in t["expense"]] + [c["display_code"] for r in t["expense"] for c in r["children"]]


def test_budget_admin_deletes_a_draft_budget(env, base, admins):
    fy = base["fy"]["id"]
    b = env.budget(fy, "3000", "Typo budget", "EXPENSE", "250.00")
    r = admins["ba"].post(f"/api/budgets/{b['id']}/delete", {"reason": "Copied by mistake"})
    assert r.status_code == 200, r.text
    assert "3000" not in _codes(env.bm, fy)
    assert "3000" not in [o["label"].split(" - ")[1] for o in env.bu.get(f"/api/budgets/filter-options?fiscal_year_id={fy}").json()]
    assert "3000 Typo budget" not in [o["label"] for o in env.selectable(fy, "WITHDRAWAL")]
    # totals do not count it
    assert env.bm.get(f"/api/budgets?fiscal_year_id={fy}").json()["expense_summary"]["amount"] == "100000.00"
    # Auditors still see it, marked Deleted, with the reason
    rows = env.auditor.get(f"/api/budgets?fiscal_year_id={fy}").json()["expense"]
    d = next(x for x in rows if x["display_code"] == "3000")
    assert d["status"] == "DELETED" and d["state"]["label"] == "Deleted"
    assert env.auditor.get(f"/api/budgets?fiscal_year_id={fy}").json()["expense_summary"]["amount"] == "100000.00"
    ev = env.auditor.get(f"/api/audit-events?action=BUDGET_DELETED&object_id={b['id']}").json()["items"]
    assert len(ev) == 1 and ev[0]["after"]["reason"] == "Copied by mistake"
    # the code is free again
    assert env.bm.post("/api/budgets", {"fiscal_year_id": fy, "code": "3000", "name": "Real budget",
                                        "budget_type": "EXPENSE", "amount": "10.00"}).status_code == 201
    # a deleted budget cannot be changed any more
    assert env.bm.patch(f"/api/budgets/{b['id']}", {"name": "x"}).status_code == 409


def test_budget_delete_rules(env, base, admins):
    fy = base["fy"]["id"]
    ba = admins["ba"]
    assert ba.post(f"/api/budgets/{base['exp']['id']}/delete", {"reason": ""}).status_code == 422      # reason required
    # allocations block it
    env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "5.00"}])
    r = ba.post(f"/api/budgets/{base['exp']['id']}/delete", {"reason": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "HAS_ALLOCATIONS"
    # sub-budgets first
    p = env.budget(fy, "4500", "Parent", "EXPENSE", "100.00")
    kid = env.budget(fy, "01", "Kid", amount="40.00", parent=p["id"])
    r = ba.post(f"/api/budgets/{p['id']}/delete", {"reason": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "HAS_SUB_BUDGETS"
    assert ba.post(f"/api/budgets/{kid['id']}/delete", {"reason": "x"}).status_code == 200
    tree = env.bm.get(f"/api/budgets?fiscal_year_id={fy}").json()
    par = next(x for x in tree["expense"] if x["display_code"] == "4500")
    assert par["other_amount"] == "100.00"                                       # Other gets the amount back
    assert ba.post(f"/api/budgets/{p['id']}/delete", {"reason": "x"}).status_code == 200
    # Budget 0 / system budgets
    b0 = env.bm.get(f"/api/budgets?fiscal_year_id={fy}").json()["budget_zero"]["id"]
    assert ba.post(f"/api/budgets/{b0}/delete", {"reason": "x"}).status_code == 422
    # only Budget Admins; others are refused even through the API
    other = env.budget(fy, "4600", "Other one", "EXPENSE", "1.00")
    for c in (env.bm, env.bu, env.ru, env.auditor, env.admin):
        assert c.post(f"/api/budgets/{other['id']}/delete", {"reason": "x"}).status_code == 403


def test_no_budget_delete_once_approved(env, base, admins):
    fy = base["fy"]["id"]
    b = env.budget(fy, "3100", "Later", "EXPENSE", "1.00")
    env.approve(fy)
    r = admins["ba"].post(f"/api/budgets/{b['id']}/delete", {"reason": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "FISCAL_YEAR_APPROVED"
    env.bm.post(f"/api/budgets/{b['id']}/unlock", {"reason": "edit"})
    assert admins["ba"].post(f"/api/budgets/{b['id']}/delete", {"reason": "x"}).status_code == 409      # unlocked too


def test_deleted_budget_not_copied(env, base, admins):
    fy = base["fy"]["id"]
    b = env.budget(fy, "3200", "Gone", "EXPENSE", "1.00")
    admins["ba"].post(f"/api/budgets/{b['id']}/delete", {"reason": "x"})
    parents = [x["id"] for x in env.bm.get(f"/api/budgets?fiscal_year_id={fy}").json()["expense"]]
    assert b["id"] not in parents
    r = env.bm.post("/api/fiscal-years", {"identifier": "2028", "start_date": "2027-07-01", "end_date": "2028-06-30",
                                          "copy_from_fiscal_year_id": fy, "copy_budget_ids": [b["id"]], "confirmations": []})
    assert r.status_code == 422


# ------------------------------------------------------------------ #53 transactions
def _ids(client, acct, **q):
    url = f"/api/register?bank_account_id={acct}" + "".join(f"&{k}={v}" for k, v in q.items())
    return [x["id"] for x in client.get(url).json()["transactions"]]


def test_register_admin_deletes_an_uncleared_transaction(env, base, admins):
    a = base["acct"]["id"]
    t = env.txn(a, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "75.00"}], check_number="1001")
    before = env.ru.get(f"/api/register?bank_account_id={a}").json()["available_balance"]
    r = admins["ra"].post(f"/api/transactions/{t['id']}/delete", {"reason": "Entered twice"})
    assert r.status_code == 200 and r.json()["status"] == "DELETED", r.text
    assert t["id"] not in _ids(env.ru, a)
    assert env.ru.get(f"/api/register?bank_account_id={a}").json()["available_balance"] == "1000.00" != before
    assert env.ru.get(f"/api/transactions/{t['id']}").status_code == 404
    # budget actuals no longer count it
    ops = next(x for x in env.bm.get(f"/api/budgets?fiscal_year_id={base['fy']['id']}").json()["expense"] if x["display_code"] == "1000")
    assert ops["actual"] == "0.00"
    # Auditors see it with the Deleted filter, with its reason
    assert t["id"] not in _ids(env.auditor, a)
    got = env.auditor.get(f"/api/register?bank_account_id={a}&status=deleted").json()["transactions"]
    assert [x["id"] for x in got] == [t["id"]] and got[0]["delete_reason"] == "Entered twice"
    assert env.auditor.get(f"/api/transactions/{t['id']}").status_code == 200
    assert env.ru.get(f"/api/register?bank_account_id={a}&status=deleted").status_code == 422   # nobody else
    ev = env.auditor.get(f"/api/audit-events?action=TRANSACTION_DELETED&object_id={t['id']}").json()["items"]
    assert len(ev) == 1 and ev[0]["after"]["delete_reason"] == "Entered twice"
    # 2.1.0 (#289, changed on purpose): deleting releases the check number - another record can use it
    r = env.ru.post("/api/transactions", {"bank_account_id": a, "transaction_type": "WITHDRAWAL", "transaction_date": "2026-08-01",
                                          "check_number": "1001", "allocations": [{"budget_id": base["exp_leaf"], "amount": "1.00"}]})
    assert r.status_code == 201, r.text
    assert got[0]["check_number"] == "1001"            # the deleted record keeps it for the Auditors
    # a deleted transaction cannot be edited or voided
    assert admins["ra"].post(f"/api/transactions/{t['id']}/delete", {"reason": "again"}).status_code == 404


def test_cleared_or_void_cannot_be_deleted(env, base, admins):
    a = base["acct"]["id"]
    t = env.txn(a, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "5.00"}], clear_date="2026-08-02")
    r = admins["ra"].post(f"/api/transactions/{t['id']}/delete", {"reason": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TRANSACTION_CLEARED"
    assert "remove it first" in r.json()["error"]["message"]
    # removing the clear date first makes it deletable
    assert env.ru.patch(f"/api/transactions/{t['id']}", {"clear_date": None, "confirmations": ["CLEARED_EDIT"]}).status_code == 200
    assert admins["ra"].post(f"/api/transactions/{t['id']}/delete", {"reason": "x"}).status_code == 200
    v = env.txn(a, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "5.00"}])
    env.ru.post(f"/api/transactions/{v['id']}/void", {"reason": "x", "confirm_irreversible": True})
    r = admins["ra"].post(f"/api/transactions/{v['id']}/delete", {"reason": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TRANSACTION_VOID"
    assert admins["ra"].post(f"/api/transactions/{v['id']}/delete", {"reason": " "}).status_code == 422


def test_only_register_admins_delete(env, base, admins):
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "5.00"}])
    for c in (env.bm, env.bu, env.ru, env.auditor, env.admin, admins["ba"]):
        assert c.post(f"/api/transactions/{t['id']}/delete", {"reason": "x"}).status_code == 403


def test_transfer_deleted_with_both_legs(env, base, admins):
    dst = env.account(account_name="Savings", atype="SAVINGS")
    r = env.ru.post("/api/transfers", {"from_account_id": base["acct"]["id"], "to_account_id": dst["id"], "amount": "10.00",
                                       "transaction_date": "2026-08-10"})
    assert r.status_code == 201, r.text
    w, d = r.json()["withdrawal"], r.json()["deposit"]
    assert admins["ra"].post(f"/api/transactions/{d['id']}/delete", {"reason": "made by mistake"}).status_code == 200
    assert w["id"] not in _ids(env.ru, base["acct"]["id"]) and d["id"] not in _ids(env.ru, dst["id"])
    ev = env.auditor.get("/api/audit-events?action=TRANSACTION_DELETED").json()["items"]
    assert sorted(int(e["object_id"]) for e in ev) == sorted([w["id"], d["id"]])


def test_closed_fiscal_year_blocks_delete(env, base, admins):
    fy = base["fy"]["id"]
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "5.00"}], clear_date="2026-08-02")
    env.approve(fy)
    env.fy_doc(fy, "AUDIT_SIGNOFF")
    assert env.bm.post(f"/api/fiscal-years/{fy}/close", {"confirm_reviewed": True}).status_code == 200
    env.ru.patch(f"/api/transactions/{t['id']}", {"clear_date": None, "confirmations": ["CLEARED_EDIT"]})
    r = admins["ra"].post(f"/api/transactions/{t['id']}/delete", {"reason": "x"})
    assert r.status_code == 409


def test_deleted_transaction_does_not_block_fiscal_year_close(env, base, admins):
    fy = base["fy"]["id"]
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "5.00"}])
    admins["ra"].post(f"/api/transactions/{t['id']}/delete", {"reason": "x"})
    env.approve(fy)
    env.fy_doc(fy, "AUDIT_SIGNOFF")
    r = env.bm.post(f"/api/fiscal-years/{fy}/close", {"confirm_reviewed": True})
    assert r.status_code == 200, r.text
