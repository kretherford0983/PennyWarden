"""2.4.0 (#251): the Invoices module switch and the Invoice Manager role (separation of duties).

BR-INV-MOD-001..004 / AC-INV-MOD-001..006 (recorded in docs/implementation-notes.md); regression for BR-002, BR-003,
BR-004, BR-078, BR-091, BR-099, BR-108 - every check exercises the API directly.
"""
from __future__ import annotations

import pytest

from conftest import png_bytes


def _module(env, on=True):
    r = env.admin.put("/api/system/modules", {"invoices": on})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def im(env):
    return env.user("invmgr", "FINANCIAL", ["INVOICE_MANAGER"])


def test_switch_is_audited_and_the_module_refuses_requests_when_off(env, im):
    """AC-INV-MOD-001 (BR-091): off by default; Administrator turns it on/off (audited); off = API refuses."""
    assert env.bm.get("/api/auth/me").json()["modules"]["invoices"] is False
    r = im.get("/api/invoices/overview")
    assert r.status_code == 404 and r.json()["error"]["code"] == "MODULE_DISABLED"
    assert env.bm.put("/api/system/modules", {"invoices": True}).status_code == 403
    assert _module(env)["invoices"] is True
    ev = env.admin.get("/api/audit-events?action=MODULE_ENABLED").json()["items"]
    assert any(e["object_id"] == "invoices" for e in ev)
    assert im.get("/api/invoices/overview").json()["can_manage"] is True
    for c in (env.bm, env.bu, env.ru, env.auditor):
        o = c.get("/api/invoices/overview")
        assert o.status_code == 200 and o.json()["can_manage"] is False
    assert env.admin.get("/api/invoices/overview").status_code == 403          # BR-003
    assert env.admin.get("/api/invoices/setup").status_code == 200              # AC-INV-MOD-006
    assert im.get("/api/invoices/setup").status_code == 403
    status = {m["key"]: m for m in env.bu.get("/api/system/modules/status").json()}
    assert status["invoices"]["enabled"] is True and "Invoice Managers" in status["invoices"]["used_by"]
    _module(env, False)
    assert im.get("/api/invoices/overview").status_code == 404


def test_role_combines_with_financial_roles_only(env):
    """AC-INV-MOD-002 (BR-002): alone or with other Financial roles; never with Administrator or Auditor."""
    env.user("im1", "FINANCIAL", ["INVOICE_MANAGER"])
    env.user("im2", "FINANCIAL", ["INVOICE_MANAGER", "BUDGET_MANAGER", "REGISTER_USER"])
    for domain, roles in (("AUDITOR", ["AUDITOR", "INVOICE_MANAGER"]), ("ADMINISTRATOR", ["ADMINISTRATOR", "INVOICE_MANAGER"]),
                          ("FINANCIAL", ["INVOICE_MANAGER", "AUDITOR"])):
        r = env.admin.post("/api/users", {"first_name": "X", "last_name": "Y", "username": f"bad{len(roles)}{domain[:2]}",
                                          "email": "x@example.com", "display_name": "X Y", "password": "Correct-Horse-9-Battery",
                                          "security_domain": domain, "roles": roles})
        assert r.status_code == 422, (domain, roles, r.text)
    ev = env.admin.get("/api/audit-events?action=USER_CREATED").json()["items"]
    assert any("INVOICE_MANAGER" in str(e["after"]) for e in ev)


def test_invoice_manager_sees_the_register_read_only_and_keeps_customers(env, base, im):
    """AC-INV-MOD-003 (BR-108 negative tests): Register read-only, normal entities yes, no budget screens, no
    Financial Institution edits, no transaction edits."""
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00"}])
    assert im.get(f"/api/register?bank_account_id={base['acct']['id']}").status_code == 200
    assert im.get(f"/api/transactions/{t['id']}").status_code == 200
    assert im.get("/api/bank-accounts").status_code == 200
    assert im.get("/api/fiscal-years").status_code == 200                      # the Register's year filter
    assert im.get(f"/api/budgets/filter-options?fiscal_year_id={base['fy']['id']}").status_code == 200
    # refused: budget and Fiscal Year screens, account details, reports, dashboard
    for url in (f"/api/fiscal-years/{base['fy']['id']}", f"/api/budgets/{base['inc']['id']}",
                f"/api/bank-accounts/{base['acct']['id']}/balance-history", "/api/dashboard",
                f"/api/fiscal-years/{base['fy']['id']}/closure-check"):
        assert im.get(url).status_code in (403, 404), url
    # no transaction edits
    r = im.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "DEPOSIT",
                                      "transaction_date": "2026-08-01",
                                      "allocations": [{"budget_id": base["inc_leaf"], "amount": "5.00"}]})
    assert r.status_code == 403
    assert im.post(f"/api/transactions/{t['id']}/void", {"reason": "x", "confirm_irreversible": True}).status_code == 403
    # customers: create and edit normal entities
    c = env.entity("Acme Customer", client=im)
    r = im.patch(f"/api/entities/{c['id']}", {"organization_name": "Acme Customer Inc."})
    assert r.status_code == 200, r.text
    # Financial Institutions: neither create nor edit
    r = im.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Some Bank",
                                  "is_financial_institution": True, "confirmations": ["DUPLICATE_ENTITY"]})
    assert r.status_code == 403
    fi = env.fi("Another Bank")
    assert im.patch(f"/api/entities/{fi['id']}", {"organization_name": "Changed"}).status_code == 403


def test_invoice_manager_sees_transaction_documents_but_not_fiscal_year_ones(env, base, im):
    """AC-INV-MOD-004 (BR-099): object-level scope for attachments."""
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00"}])
    r = env.ru.c.post(f"/api/attachments?owner_type=transaction&owner_id={t['id']}", files={"file": ("r.png", png_bytes())},
                      headers={"X-CSRF-Token": env.ru.csrf})
    assert r.status_code == 201
    att = r.json()
    assert im.get(f"/api/attachments?owner_type=transaction&owner_id={t['id']}").status_code == 200
    assert im.get(f"/api/attachments/{att['id']}/content").status_code == 200
    doc = env.fy_doc(base["fy"]["id"])
    assert im.get(f"/api/attachments?owner_type=fiscal_year&owner_id={base['fy']['id']}").status_code == 403
    assert im.get(f"/api/attachments/{doc['id']}/content").status_code == 403
    assert im.c.post(f"/api/attachments?owner_type=transaction&owner_id={t['id']}", files={"file": ("x.png", png_bytes((3, 3)))},
                     headers={"X-CSRF-Token": im.csrf}).status_code == 403


def test_security_overview_lists_the_whole_cycle(env):
    """AC-INV-MOD-005: informational (never attention)."""
    env.user("allinone", "FINANCIAL", ["BUDGET_MANAGER", "INVOICE_MANAGER", "REGISTER_USER"])
    env.user("split", "FINANCIAL", ["INVOICE_MANAGER", "REGISTER_USER"])
    items = {i["key"]: i for i in env.admin.get("/api/system/security-overview").json()["items"]}
    w = items["whole_cycle"]
    assert w["value"] == "1" and "allinone" in w["note"] and w["status"] == "info"
    assert "split," not in w["note"] and ": split" not in w["note"]
