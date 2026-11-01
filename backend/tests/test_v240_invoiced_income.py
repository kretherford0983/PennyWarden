"""2.4.0 (#250): Invoiced Income budgets - a flag on an Income parent budget, carried by its family.

BR-INV-INC-001..003 / AC-INV-INC-001..005 (recorded in docs/implementation-notes.md); regression for BR-016, BR-023/024,
BR-027, BR-050 (no exception without the Invoices module), BR-075..078, BR-079, BR-098, BR-108.
"""
from __future__ import annotations


def _set(client, bid, on=True):
    return client.put(f"/api/budgets/{bid}/invoiced-income", {"invoiced_income": on})


def _row(env, fy_id, bid):
    tree = env.bu.get(f"/api/fiscal-years/{fy_id}").json()
    rows = tree.get("budgets") or tree
    for kind in ("income", "expense"):
        for r in rows[kind]:
            for x in [r, *r.get("children", [])]:
                if x["id"] == bid:
                    return x
    raise AssertionError(f"budget {bid} not found")


def test_set_and_clear_on_income_parent_family_carries_it(env, base):
    """AC-INV-INC-001: Budget Manager sets/clears on an Income parent; sub-budgets and Other inherit; audited."""
    inc = base["inc"]
    child = env.budget(base["fy"]["id"], "01", "Invoices A", parent=inc["id"], amount="100.00")
    r = _set(env.bm, inc["id"])
    assert r.status_code == 200, r.text
    assert r.json()["invoiced_income"] is True
    assert _row(env, base["fy"]["id"], child["id"])["invoiced_income"] is True
    # a sub-budget added later inherits it
    later = env.budget(base["fy"]["id"], "02", "Invoices B", parent=inc["id"], amount="50.00")
    assert later["invoiced_income"] is True
    ev = env.auditor.get(f"/api/audit-events?action=BUDGET_INVOICED_INCOME_SET&object_id={inc['id']}").json()["items"]
    assert len(ev) == 1 and ev[0]["before"]["invoiced_income"] is False and ev[0]["after"]["invoiced_income"] is True
    assert _set(env.bm, inc["id"], False).json()["invoiced_income"] is False
    assert _row(env, base["fy"]["id"], child["id"])["invoiced_income"] is False
    assert env.auditor.get("/api/audit-events?action=BUDGET_INVOICED_INCOME_CLEARED").json()["items"]


def test_refused_for_expense_children_other_and_other_roles(env, base):
    """AC-INV-INC-002 / BR-108: only an Income parent, only a Budget Manager (API, not just UI)."""
    assert _set(env.bm, base["exp"]["id"]).status_code == 422
    child = env.budget(base["fy"]["id"], "01", "Invoices A", parent=base["inc"]["id"], amount="100.00")
    assert _set(env.bm, child["id"]).status_code == 422
    if base["inc_leaf"] != base["inc"]["id"]:          # the simple budget's selectable leaf is its Other
        assert _set(env.bm, base["inc_leaf"]).status_code == 422
    for c in (env.bu, env.ru, env.auditor, env.admin):
        assert _set(c, base["inc"]["id"]).status_code == 403
    # mass assignment: not settable through create / edit
    r = env.bm.patch(f"/api/budgets/{base['inc']['id']}", {"name": "Donations", "invoiced_income": True})
    assert r.status_code == 422
    r = env.bm.post("/api/budgets", {"fiscal_year_id": base["fy"]["id"], "code": "4500", "name": "Sales",
                                     "budget_type": "INCOME", "amount": "10.00", "invoiced_income": True})
    assert r.status_code == 422


def test_approved_budget_needs_unlock_with_reason_first(env, base):
    """AC-INV-INC-003 (BR-023/024): on an Approved, locked budget the flag changes only after an audited unlock."""
    env.approve(base["fy"]["id"])
    r = _set(env.bm, base["inc"]["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "BUDGET_LOCKED"
    assert env.bm.post(f"/api/budgets/{base['inc']['id']}/unlock", {"reason": "Mark for invoices"}).status_code == 200
    assert _set(env.bm, base["inc"]["id"]).status_code == 200
    assert env.bm.post(f"/api/budgets/{base['inc']['id']}/lock").status_code == 200
    assert _set(env.bm, base["inc"]["id"], False).status_code == 409


def test_copy_carries_the_flag(env, base):
    """AC-INV-INC-004 (BR-027): a copied budget keeps Invoiced Income."""
    _set(env.bm, base["inc"]["id"])
    r = env.bm.post("/api/fiscal-years", {"identifier": "2028", "start_date": "2027-07-01", "end_date": "2028-06-30",
                                          "copy_from_fiscal_year_id": base["fy"]["id"],
                                          "copy_budget_ids": [base["inc"]["id"], base["exp"]["id"]]})
    assert r.status_code == 201, r.text
    fy28 = r.json()["id"]
    tree = env.bu.get(f"/api/fiscal-years/{fy28}").json()
    rows = tree.get("budgets") or tree
    inc = [x for x in rows["income"] if x["code"] == base["inc"]["parent_code"]][0]
    exp = [x for x in rows["expense"] if x["code"] == base["exp"]["parent_code"]][0]
    assert inc["invoiced_income"] is True and exp["invoiced_income"] is False


def test_no_effect_on_register_entry_without_the_module(env, base):
    """AC-INV-INC-005 (BR-050 unchanged): deposits on an Invoiced Income budget save as before; it counts as income."""
    _set(env.bm, base["inc"]["id"])
    t = env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "25.00"}])
    assert t["status"] == "ACTIVE"
    assert _row(env, base["fy"]["id"], base["inc"]["id"])["actual"] == "25.00"
    # a withdrawal still can't use it (no refund exception without the module)
    r = env.ru.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "WITHDRAWAL",
                                          "transaction_date": "2026-08-02",
                                          "allocations": [{"budget_id": base["inc_leaf"], "amount": "5.00"}]})
    assert r.status_code == 422
