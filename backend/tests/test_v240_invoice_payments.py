"""2.4.0 (#254): invoice payments - Record payment, link, unlink, overpayment refund, void re-opens.

BR-INV-PAY-001..006 / AC-INV-PAY-001..007 (recorded in docs/implementation-notes.md); regression for BR-045..050
(BR-050 amended for refunds only), BR-057, BR-063, BR-066/068, BR-077, BR-099, BR-108, AC-REG-008.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def ib(env, base):
    assert env.admin.put("/api/system/modules", {"invoices": True}).status_code == 200
    im = env.user("invmgr", "FINANCIAL", ["INVOICE_MANAGER"])
    assert env.bm.put(f"/api/budgets/{base['inc']['id']}/invoiced-income", {"invoiced_income": True}).status_code == 200
    units = {u["name"]: u["id"] for u in im.get("/api/invoices/catalog/unit-types").json()}
    dues = im.post("/api/invoices/catalog/products", {"name": "Dues", "unit_price": "100.00", "unit_type_id": units["Year"],
                                                     "budget_id": base["inc_leaf"], "taxable": True}).json()["id"]
    tax = im.post("/api/invoices/catalog/tax-rates", {"name": "Tax", "rate": "10", "budget_id": base["inc_leaf"]}).json()["id"]
    cust = env.entity("Paying Customer", client=im)["id"]
    i = im.post("/api/invoices", {"customer_entity_id": cust, "invoice_date": "2026-09-15", "tax_rate_id": tax,
                                  "lines": [{"product_id": dues, "quantity": "2"}]}).json()       # 200 + 20 tax = 220
    assert im.post(f"/api/invoices/{i['id']}/send").json()["status"] == "SENT"
    return {"im": im, "inv": i["id"], "cust": cust, "acct": base["acct"]["id"], "dues": dues, "tax": tax}


def _pay(env, ib, amount, **kw):
    return env.ru.post(f"/api/invoices/{ib['inv']}/payments", {"bank_account_id": ib["acct"], "amount": amount,
                                                               "transaction_date": "2026-09-20", **kw})


def _inc_actual(env, base):
    tree = env.bu.get(f"/api/fiscal-years/{base['fy']['id']}").json()
    rows = (tree.get("budgets") or tree)["income"]
    return [r for r in rows if r["id"] == base["inc"]["id"]][0]["actual"]


def test_record_partial_then_full_payment(env, base, ib):
    """AC-INV-PAY-001: deposits pre-filled on the Invoiced Income budgets; Partly paid then Paid; budgets move only
    when the deposit is recorded."""
    assert _inc_actual(env, base) == "0.00"
    r = _pay(env, ib, "110.00")
    assert r.status_code == 201, r.text
    assert r.json()["invoice"]["status"] == "PARTLY_PAID" and r.json()["invoice"]["payments"]["paid"] == "110.00"
    t = r.json()["transaction"]
    assert t["transaction_type"] == "DEPOSIT" and t["total"] == "110.00"
    # 110 of 220: tax in proportion (10.00), lines get 100.00
    amounts = sorted(a["amount"] for a in t["allocations"])
    assert amounts == ["10.00", "100.00"]
    assert _inc_actual(env, base) == "110.00"
    r = _pay(env, ib, "110.00")
    assert r.status_code == 409 and r.json()["error"]["warnings"][0]["code"] == "POSSIBLE_DUPLICATE"   # BR register warning
    r = _pay(env, ib, "110.00", confirmations=["POSSIBLE_DUPLICATE"])
    assert r.status_code == 201, r.text
    assert r.json()["invoice"]["status"] == "PAID" and r.json()["invoice"]["payments"]["open"] == "0.00"
    assert env.auditor.get(f"/api/audit-events?action=INVOICE_PAYMENT_RECORDED&object_id={ib['inv']}").json()["items"]


def test_overpayment_and_refund_with_the_br050_exception(env, base, ib):
    """AC-INV-PAY-004: overpayment allocation; refund capped at the overage; reduces the Invoiced Income budget; the
    exception is refused anywhere else."""
    r = _pay(env, ib, "250.00")
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    r = _pay(env, ib, "250.00", confirm_overpayment=True)
    assert r.status_code == 201, r.text
    inv = r.json()["invoice"]
    assert inv["status"] == "PAID" and inv["payments"]["overpaid"] == "30.00"
    assert any(x["kind"] == "OVERPAYMENT" for x in inv["payments"]["links"])
    assert _inc_actual(env, base) == "250.00"
    bad = env.ru.post(f"/api/invoices/{ib['inv']}/refunds", {"bank_account_id": ib["acct"], "amount": "31.00"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "OVER_REFUNDABLE"
    ok = env.ru.post(f"/api/invoices/{ib['inv']}/refunds", {"bank_account_id": ib["acct"], "amount": "30.00",
                                                             "transaction_date": "2026-09-25", "check_number": "5001"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["transaction"]["transaction_type"] == "WITHDRAWAL"
    assert _inc_actual(env, base) == "220.00"                  # the refund reduces the income
    assert ok.json()["invoice"]["payments"]["refundable"] == "0.00"
    # the exception is refused for a plain register withdrawal on the same Income budget
    r = env.ru.post("/api/transactions", {"bank_account_id": ib["acct"], "transaction_type": "WITHDRAWAL",
                                          "transaction_date": "2026-09-26",
                                          "allocations": [{"budget_id": base["inc_leaf"], "amount": "1.00"}]})
    assert r.status_code == 422


def test_register_refuses_unlinked_invoiced_income_deposits_and_locks_linked_lines(env, base, ib):
    """AC-INV-PAY-003: with the module on, a hand-entered deposit on Invoiced Income is refused; a linked line can't
    change amount or budget in the register; without the module it is allowed."""
    r = env.ru.post("/api/transactions", {"bank_account_id": ib["acct"], "transaction_type": "DEPOSIT",
                                          "transaction_date": "2026-09-20",
                                          "allocations": [{"budget_id": base["inc_leaf"], "amount": "5.00"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVOICE_PAYMENT_REQUIRED"
    t = _pay(env, ib, "50.00").json()["transaction"]
    a = t["allocations"][0]
    upd = env.ru.patch(f"/api/transactions/{t['id']}", {"allocations": [
        {"id": x["id"], "budget_id": x["budget_id"], "amount": "1.00" if x["id"] == a["id"] else x["amount"]}
        for x in t["allocations"]]})
    assert upd.status_code == 409 and upd.json()["error"]["code"] == "LINKED_TO_INVOICE"
    notes = env.ru.patch(f"/api/transactions/{t['id']}", {"notes": "Paid at the door"})
    assert notes.status_code == 200
    env.admin.put("/api/system/modules", {"invoices": False})
    r = env.ru.post("/api/transactions", {"bank_account_id": ib["acct"], "transaction_type": "DEPOSIT",
                                          "transaction_date": "2026-09-20",
                                          "allocations": [{"budget_id": base["inc_leaf"], "amount": "5.00"}]})
    assert r.status_code == 201


def test_link_existing_deposit_capped_and_needs_invoiced_income(env, base, ib):
    """AC-INV-PAY-002: a deposit not on Invoiced Income must be re-allocated first; a link can't exceed the open
    balance; another payer is a warning; Invoice Manager may link, not record."""
    other = env.budget(base["fy"]["id"], "4100", "Grants", "INCOME", "500.00")
    sel = {o["label"]: o["id"] for o in env.selectable(base["fy"]["id"], "DEPOSIT")}
    t = env.txn(ib["acct"], "DEPOSIT", [{"budget_id": sel["4100 Grants"], "amount": "50.00"}], date="2026-09-20")
    r = ib["im"].post(f"/api/invoices/{ib['inv']}/links", {"allocation_id": t["allocations"][0]["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_INVOICED_INCOME"
    # a deposit entered before the module was on, on the Invoiced Income budget
    env.admin.put("/api/system/modules", {"invoices": False})
    big = env.txn(ib["acct"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "500.00"}], date="2026-09-21")
    small = env.txn(ib["acct"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "60.00"}], date="2026-09-21")
    env.admin.put("/api/system/modules", {"invoices": True})
    r = ib["im"].post(f"/api/invoices/{ib['inv']}/links", {"allocation_id": big["allocations"][0]["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "OVER_OPEN_BALANCE"
    r = ib["im"].post(f"/api/invoices/{ib['inv']}/links", {"allocation_id": small["allocations"][0]["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"     # no entity = third party
    r = ib["im"].post(f"/api/invoices/{ib['inv']}/links", {"allocation_id": small["allocations"][0]["id"],
                                                          "confirmations": ["THIRD_PARTY_PAYER"]})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "PARTLY_PAID" and r.json()["payments"]["paid"] == "60.00"
    assert ib["im"].post(f"/api/invoices/{ib['inv']}/payments", {"bank_account_id": ib["acct"], "amount": "1"}).status_code == 403
    for c in (env.bm, env.bu, env.auditor):
        assert c.post(f"/api/invoices/{ib['inv']}/links", {"allocation_id": small["allocations"][0]["id"]}).status_code == 403
        assert c.post(f"/api/invoices/{ib['inv']}/payments", {"bank_account_id": ib["acct"], "amount": "1"}).status_code == 403
    assert other["id"]


def test_void_reopens_and_unlink_moves_the_line(env, base, ib):
    """AC-INV-PAY-005: voiding a linked deposit re-opens the invoice atomically; unlink moves the line to another
    budget in the same step (Register User only)."""
    t = _pay(env, ib, "220.00").json()["transaction"]
    assert env.ru.get(f"/api/invoices/{ib['inv']}").json()["status"] == "PAID"
    v = env.ru.post(f"/api/transactions/{t['id']}/void", {"reason": "Bounced", "confirm_irreversible": True})
    assert v.status_code == 200, v.text
    assert env.ru.get(f"/api/invoices/{ib['inv']}").json()["status"] == "SENT"
    assert env.auditor.get(f"/api/audit-events?action=INVOICE_STATUS_CHANGED&object_id={ib['inv']}").json()["items"]
    t2 = _pay(env, ib, "100.00").json()
    link = [x for x in t2["invoice"]["payments"]["links"] if not x["unlinked"] and x["status"] == "ACTIVE"][0]
    grants = env.budget(base["fy"]["id"], "4100", "Grants", "INCOME", "500.00")
    sel = {o["label"]: o["id"] for o in env.selectable(base["fy"]["id"], "DEPOSIT")}
    assert ib["im"].post(f"/api/invoices/{ib['inv']}/links/{link['id']}/unlink",
                         {"move_to_budget_id": sel["4100 Grants"], "reason": "Was a grant"}).status_code == 403
    r = env.ru.post(f"/api/invoices/{ib['inv']}/links/{link['id']}/unlink", {"move_to_budget_id": base["inc_leaf"], "reason": "x"})
    assert r.status_code == 422                                  # not to another Invoiced Income budget
    r = env.ru.post(f"/api/invoices/{ib['inv']}/links/{link['id']}/unlink", {"move_to_budget_id": sel["4100 Grants"],
                                                                              "reason": "It was a grant"})
    assert r.status_code == 200, r.text
    assert grants["id"]


def test_revision_cannot_go_below_paid_and_void_refused_with_payments(env, ib):
    """AC-INV-PAY-006: proposed rules confirmed by the build - revision total >= paid; no void once paid."""
    _pay(env, ib, "150.00")
    assert ib["im"].post(f"/api/invoices/{ib['inv']}/void", {"reason": "x"}).status_code == 409
    r = ib["im"].post(f"/api/invoices/{ib['inv']}/revise", {"reason": "Fewer items"}).json()
    lines = [{"id": r["lines"][0]["id"], "product_id": ib["dues"], "quantity": "1"}]     # 110 total < 150 paid
    u = ib["im"].put(f"/api/invoices/{ib['inv']}", {"customer_entity_id": ib["cust"], "invoice_date": "2026-09-15",
                                                     "tax_rate_id": ib["tax"], "lines": lines})
    assert u.status_code == 422
    lines[0]["quantity"] = "3"
    u = ib["im"].put(f"/api/invoices/{ib['inv']}", {"customer_entity_id": ib["cust"], "invoice_date": "2026-09-15",
                                                     "tax_rate_id": ib["tax"], "lines": lines})
    assert u.status_code == 200
    s = ib["im"].post(f"/api/invoices/{ib['inv']}/send").json()
    assert s["status"] == "PARTLY_PAID" and s["payments"]["open"] == "180.00"


def test_object_scope(env, ib):
    """AC-INV-PAY-007 (BR-099): unknown ids; a draft can't take a payment."""
    assert env.ru.post("/api/invoices/999999/payments", {"bank_account_id": ib["acct"], "amount": "1"}).status_code == 404
    assert ib["im"].post(f"/api/invoices/{ib['inv']}/links", {"allocation_id": 999999}).status_code == 404
    d = ib["im"].post("/api/invoices", {"customer_entity_id": ib["cust"], "invoice_date": "2026-09-15",
                                        "lines": [{"product_id": ib["dues"], "quantity": "1"}]}).json()
    r = env.ru.post(f"/api/invoices/{d['id']}/payments", {"bank_account_id": ib["acct"], "amount": "1"})
    assert r.status_code == 409
