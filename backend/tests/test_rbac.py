"""Role separation and direct API authorization. AC-SEC-003, AC-SEC-004, AC-SEC-005, AC-SEC-007, AC-SEC-014."""
from conftest import PDF_BYTES


def _setup(env, base):
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00"}])
    ent = env.entity()
    att = env.bm.c.post(f"/api/attachments?owner_type=fiscal_year&owner_id={base['fy']['id']}",
                        files={"file": ("doc.pdf", PDF_BYTES, "application/pdf")},
                        headers={"X-CSRF-Token": env.bm.csrf}).json()
    return t, ent, att


def test_ac_sec_003_admin_financial_isolation(env, base):
    t, ent, att = _setup(env, base)
    fy, acct = base["fy"]["id"], base["acct"]["id"]
    urls = ["/api/fiscal-years", f"/api/fiscal-years/{fy}", f"/api/budgets?fiscal_year_id={fy}",
            f"/api/budgets/selectable?fiscal_year_id={fy}", f"/api/budgets/{base['exp']['id']}", "/api/entities",
            f"/api/entities/{ent['id']}", "/api/bank-accounts", f"/api/bank-accounts/{acct}",
            f"/api/register?bank_account_id={acct}", f"/api/transactions/{t['id']}", "/api/fiscal-year-reviews",
            f"/api/attachments?owner_type=fiscal_year&owner_id={fy}", f"/api/attachments/{att['id']}",
            f"/api/attachments/{att['id']}/content", f"/api/fiscal-years/{fy}/closure-check",
            "/api/fiscal-years/natural?date=2026-08-01"]
    for u in urls:
        assert env.admin.get(u).status_code == 403, u
    assert env.admin.get("/api/dashboard").json()["kind"] == "administrator"
    assert "bank_accounts" not in env.admin.get("/api/dashboard").json()
    # admin audit view withholds financial snapshots
    items = env.admin.get("/api/audit-events?object_type=register_transaction").json()["items"]
    assert items and all(i["before"] is None and i["after"] is None and i["snapshots_withheld"] for i in items)
    # admin cannot mutate financial data
    assert env.admin.post("/api/fiscal-years", {"identifier": "X1", "start_date": "2030-01-01",
                                                "end_date": "2030-12-31"}).status_code == 403
    assert env.admin.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Z"}).status_code == 403


def test_ac_sec_004_auditor_read_only(env, base):
    t, ent, att = _setup(env, base)
    env.ru.post(f"/api/entities/{ent['id']}/inactivate", {})
    env.bm.post(f"/api/budgets/{base['inc']['id']}/reject", {"reason": "no"})
    env.ru.post(f"/api/transactions/{t['id']}/void", {"reason": "dup", "confirm_irreversible": True})
    a = env.auditor
    assert a.get("/api/users").status_code == 200
    assert a.get("/api/audit-events").json()["items"][0]["snapshots_withheld"] is False
    assert any(e["id"] == ent["id"] for e in a.get("/api/entities?status=inactive").json())
    tree = a.get(f"/api/budgets?fiscal_year_id={base['fy']['id']}").json()
    assert tree["income"][0]["status"] == "REJECTED"
    reg = a.get(f"/api/register?bank_account_id={base['acct']['id']}&status=void").json()
    assert reg["transactions"][0]["status"] == "VOID"
    assert a.get(f"/api/attachments/{att['id']}/content").status_code == 200
    assert a.get("/api/dashboard").json()["kind"] == "auditor"
    # no mutation anywhere
    fy = base["fy"]["id"]
    attempts = [
        ("post", "/api/fiscal-years", {"identifier": "A1", "start_date": "2030-01-01", "end_date": "2030-12-31"}),
        ("post", f"/api/fiscal-years/{fy}/approve", {"confirm_irreversible": True}),
        ("post", "/api/budgets", {"fiscal_year_id": fy, "code": "9", "name": "x", "budget_type": "EXPENSE", "amount": "1"}),
        ("post", "/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Q"}),
        ("patch", f"/api/entities/{ent['id']}", {"notes": "x"}),
        ("post", f"/api/bank-accounts/{base['acct']['id']}/reveal", None),
        ("post", "/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "DEPOSIT",
                                       "allocations": [{"budget_id": base["inc_leaf"], "amount": "1"}]}),
        ("post", "/api/users", {"first_name": "Test", "last_name": "Person", "username": "zzz", "email": "z@z.org", "password": "Abcdefgh1234",
                                "security_domain": "AUDITOR", "roles": ["AUDITOR"]}),
        ("put", "/api/me/preferences", {"theme": "dark"}),
    ]
    for m, url, body in attempts[:-1]:
        assert getattr(a, m)(url, body).status_code == 403, url
    # own preference is not application data; auditors may set their theme
    assert a.put("/api/me/preferences", {"theme": "dark"}).status_code == 200


def test_ac_sec_005_permission_matrix_direct_api(env, base):
    fy = base["fy"]["id"]
    # Budget User: read only
    assert env.bu.get(f"/api/fiscal-years/{fy}").status_code == 200
    assert env.bu.post("/api/budgets", {"fiscal_year_id": fy, "code": "7", "name": "x", "budget_type": "EXPENSE",
                                        "amount": "1"}).status_code == 403
    assert env.bu.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Q"}).status_code == 403
    assert env.bu.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "DEPOSIT",
                                             "allocations": [{"budget_id": base["inc_leaf"], "amount": "1"}]}).status_code == 403
    assert env.bu.get("/api/users").status_code == 403
    assert env.bu.get("/api/audit-events").status_code == 403
    # Budget Manager cannot create/edit/void transactions
    assert env.bm.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "DEPOSIT",
                                             "allocations": [{"budget_id": base["inc_leaf"], "amount": "1"}]}).status_code == 403
    assert env.bm.get(f"/api/register?bank_account_id={base['acct']['id']}").status_code == 200
    # Register User cannot manage FYs, budgets, bank accounts, or reveal
    assert env.ru.post(f"/api/fiscal-years/{fy}/approve", {"confirm_irreversible": True}).status_code == 403
    assert env.ru.post(f"/api/bank-accounts/{base['acct']['id']}/reveal").status_code == 403
    assert env.ru.patch(f"/api/bank-accounts/{base['acct']['id']}", {"account_name": "x"}).status_code == 403
    assert env.ru.get("/api/users").status_code == 403
    # Financial users cannot administer users
    assert env.bm.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "zzz", "email": "z@z.org", "password": "Abcdefgh1234",
                                      "security_domain": "FINANCIAL", "roles": ["BUDGET_MANAGER"]}).status_code == 403
    # unauthenticated
    from conftest import Api
    anon = Api(env.app)
    assert anon.get("/api/fiscal-years").status_code == 401


def test_ac_sec_007_financial_institution_maintenance(env):
    r = env.ru.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Credit Union",
                                      "is_financial_institution": True})
    assert r.status_code == 201
    eid = r.json()["id"]
    assert env.ru.patch(f"/api/entities/{eid}", {"notes": "x"}).status_code == 403
    assert env.ru.patch(f"/api/entities/{eid}", {"is_financial_institution": False}).status_code == 403
    assert env.ru.post(f"/api/entities/{eid}/inactivate", {}).status_code == 403
    assert env.bm.get(f"/api/entities/{eid}").json()["is_financial_institution"] is True
    assert env.bm.patch(f"/api/entities/{eid}", {"notes": "ok"}).status_code == 200
    assert env.bm.post(f"/api/entities/{eid}/inactivate", {}).status_code == 200
    assert env.ru.post(f"/api/entities/{eid}/restore", {}).status_code == 403
    assert env.bm.post(f"/api/entities/{eid}/restore", {}).status_code == 200
    assert env.bm.patch(f"/api/entities/{eid}", {"is_financial_institution": False}).status_code == 200
    # ordinary entity: register user can maintain it
    assert env.ru.patch(f"/api/entities/{eid}", {"notes": "now ordinary"}).status_code == 200


def test_ac_sec_014_object_level_authorization(env, base):
    # hidden system Multiple entity cannot be fetched/edited by id substitution
    ents = env.bm.get("/api/entities?status=all").json()
    ids = {e["id"] for e in ents}
    for probe in range(1, max(ids) + 3):
        if probe not in ids:
            assert env.bm.get(f"/api/entities/{probe}").status_code == 404
            assert env.bm.patch(f"/api/entities/{probe}", {"notes": "x"}).status_code == 404
    # non-existent / out-of-scope ids return 404 without leaking data
    for u in ["/api/transactions/99999", "/api/bank-accounts/99999", "/api/budgets/99999", "/api/fiscal-years/99999",
              "/api/attachments/99999"]:
        assert env.auditor.get(u).status_code == 404
    # an allocation id belonging to another transaction cannot be edited through this transaction
    t1 = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00"}])
    t2 = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "20.00"}])
    other_alloc = t2["allocations"][0]["id"]
    r = env.ru.patch(f"/api/transactions/{t1['id']}", {"allocations": [
        {"id": other_alloc, "budget_id": base["exp_leaf"], "amount": "5.00"}]})
    assert r.status_code == 422
    assert env.ru.get(f"/api/transactions/{t2['id']}").json()["total"] == "20.00"
    # a user cannot target another workspace's objects: workspace_id is not an accepted field
    r = env.ru.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "W", "workspace_id": 999})
    assert r.status_code == 422
