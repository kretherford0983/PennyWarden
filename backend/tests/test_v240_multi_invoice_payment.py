"""2.4.0 (#523): one payment for several invoices - one deposit, linked to each invoice. Decisions (Kyle,
2026-11-04): start from a customer's open invoices or a typed invoice number; oldest due first; overpayment confirmed
onto a chosen invoice; another payer than a customer confirmed (THIRD_PARTY_PAYER); void and unlink per invoice.
BR-INV-PAY-007..009 / AC-INV-PAY-008..011 (docs/implementation-notes.md)."""
from __future__ import annotations

import pytest

from test_v240_invoice_payments import ib  # noqa: F401  (fixture)

URL = "/api/invoices/payments"


def _invoice(ib, cust, qty, date, due=None):
    body = {"customer_entity_id": cust, "invoice_date": date, "lines": [{"product_id": ib["dues"], "quantity": qty}]}
    if due:
        body["due_date"] = due
    i = ib["im"].post("/api/invoices", body)
    assert i.status_code == 201, i.text
    assert ib["im"].post(f"/api/invoices/{i.json()['id']}/send").status_code == 200
    return i.json()["id"]


@pytest.fixture
def three(env, ib):
    """Paying Customer: the fixture's invoice (220.00, dated 2026-09-15) and two more (110.00 and 330.00)."""
    b = _invoice(ib, ib["cust"], "1", "2026-09-01")            # 110.00, the oldest
    c = _invoice(ib, ib["cust"], "3", "2026-09-20")            # 330.00
    return {"a": ib["inv"], "b": b, "c": c}


def _post(env, ib, items, **kw):
    return env.ru.post(URL, {"bank_account_id": ib["acct"], "transaction_date": "2026-09-25",
                             "items": [{"invoice_id": i, "amount": a} for i, a in items], **kw})


def test_ac_inv_pay_008_open_invoices_oldest_due_first_and_by_number(env, ib, three):
    r = env.ru.get(f"{URL}/open", params={"customer_entity_id": ib["cust"]})
    assert r.status_code == 200, r.text
    rows = r.json()["invoices"]
    assert [x["id"] for x in rows] == [three["b"], three["a"], three["c"]]       # due dates follow invoice dates
    assert [x["open"] for x in rows] == ["110.00", "220.00", "330.00"]
    num = rows[2]["number"]
    by = env.ru.get(f"{URL}/open", params={"number": num.lower()}).json()       # typed off a payment stub
    assert by["found_invoice_id"] == three["c"] and len(by["invoices"]) == 3
    assert env.ru.get(f"{URL}/open", params={"number": "NOPE-1"}).status_code == 404
    assert ib["im"].get(f"{URL}/open", params={"customer_entity_id": ib["cust"]}).status_code == 403   # Register User


def test_ac_inv_pay_009_one_deposit_linked_to_each_invoice(env, base, ib, three):
    r = _post(env, ib, [(three["b"], "110.00"), (three["a"], "220.00"), (three["c"], "100.00")])
    assert r.status_code == 201, r.text
    t = r.json()["transaction"]
    assert t["transaction_type"] == "DEPOSIT" and t["total"] == "430.00"        # one deposit = the check
    st = {i["id"]: (i["status"], i["payments"]["paid"]) for i in r.json()["invoices"]}
    assert st == {three["b"]: ("PAID", "110.00"), three["a"]: ("PAID", "220.00"), three["c"]: ("PARTLY_PAID", "100.00")}
    # each invoice's lines are linked to it, and add up to its part
    for iid, part in ((three["b"], "110.00"), (three["a"], "220.00"), (three["c"], "100.00")):
        links = env.ru.get(f"/api/invoices/{iid}").json()["payments"]["links"]
        assert {x["transaction_id"] for x in links} == {t["id"]}
        assert f"{sum(float(x['amount']) for x in links):.2f}" == part
    ev = env.auditor.get(f"/api/audit-events?action=INVOICE_PAYMENT_RECORDED&object_id={three['c']}").json()["items"]
    assert ev and ev[0]["after"]["invoices_in_deposit"] == 3
    # what is left, as Record payment would leave it: the rest pays invoice C exactly
    r = env.ru.post(f"/api/invoices/{three['c']}/payments", {"bank_account_id": ib["acct"], "amount": "230.00",
                                                             "transaction_date": "2026-09-26"})
    assert r.status_code == 201 and r.json()["invoice"]["status"] == "PAID"


def test_ac_inv_pay_010_overpayment_balances_and_another_payer(env, ib, three):
    r = _post(env, ib, [(three["b"], "120.00")])
    assert r.status_code == 422 and r.json()["error"]["code"] == "OVER_OPEN_BALANCE"
    r = _post(env, ib, [(three["b"], "110.00"), (three["b"], "1.00")])
    assert r.status_code == 422                                                   # each invoice once
    r = _post(env, ib, [(three["b"], "110.00")], overpayment="15.00")
    assert r.status_code == 422                                                   # which invoice gets it
    r = _post(env, ib, [(three["b"], "110.00")], overpayment="15.00", overpayment_invoice_id=three["b"])
    assert r.status_code == 409 and r.json()["error"]["warnings"][0]["code"] == "OVERPAYMENT"
    r = _post(env, ib, [(three["b"], "110.00")], overpayment="15.00", overpayment_invoice_id=three["b"],
              confirm_overpayment=True)
    assert r.status_code == 201, r.text
    assert r.json()["invoices"][0]["payments"]["overpaid"] == "15.00" and r.json()["transaction"]["total"] == "125.00"
    # a parent or company paying for another customer's invoice: who paid, then a confirmation
    other = env.entity("Other Member", client=ib["im"])["id"]
    d = _invoice(ib, other, "1", "2026-09-05")
    r = _post(env, ib, [(three["a"], "220.00"), (d, "110.00")])
    assert r.status_code == 422 and r.json()["error"]["errors"][0]["field"] == "payer_entity_id"
    r = _post(env, ib, [(three["a"], "220.00"), (d, "110.00")], payer_entity_id=ib["cust"])
    assert r.status_code == 409 and r.json()["error"]["warnings"][0]["code"] == "THIRD_PARTY_PAYER"
    r = _post(env, ib, [(three["a"], "220.00"), (d, "110.00")], payer_entity_id=ib["cust"],
              confirmations=["THIRD_PARTY_PAYER"])
    assert r.status_code == 201, r.text
    t = r.json()["transaction"]
    assert t["entity"]["id"] == ib["cust"]                                     # the deposit is the payer's
    assert {a["entity"]["id"] for a in t["allocations"]} == {ib["cust"]}


def test_ac_inv_pay_011_void_and_unlink_stay_per_invoice(env, base, ib, three):
    t = _post(env, ib, [(three["b"], "110.00"), (three["a"], "220.00")]).json()["transaction"]
    # unlink on one invoice: only its lines move; the other stays paid
    grants = env.budget(base["fy"]["id"], "4100", "Grants", "INCOME", "500.00")
    sel = {o["label"]: o["id"] for o in env.selectable(base["fy"]["id"], "DEPOSIT")}
    links = env.ru.get(f"/api/invoices/{three['b']}").json()["payments"]["links"]
    for x in links:
        r = env.ru.post(f"/api/invoices/{three['b']}/links/{x['id']}/unlink",
                        {"move_to_budget_id": sel["4100 Grants"], "reason": "Was a grant"})
        assert r.status_code == 200, r.text
    assert env.ru.get(f"/api/invoices/{three['b']}").json()["status"] == "SENT"
    assert env.ru.get(f"/api/invoices/{three['a']}").json()["status"] == "PAID"
    # void the deposit: every invoice it still pays re-opens
    v = env.ru.post(f"/api/transactions/{t['id']}/void", {"reason": "Bounced", "confirm_irreversible": True})
    assert v.status_code == 200, v.text
    assert env.ru.get(f"/api/invoices/{three['a']}").json()["status"] == "SENT"
    assert grants["id"]


def test_multi_payment_needs_the_module_and_a_register_user(env, ib, three):
    assert _post(env, ib, [(three["b"], "10.00")], ).status_code == 201
    r = ib["im"].post(URL, {"bank_account_id": ib["acct"], "items": [{"invoice_id": three["b"], "amount": "10.00"}]})
    assert r.status_code == 403
    assert env.admin.put("/api/system/modules", {"invoices": False}).status_code == 200
    assert _post(env, ib, [(three["b"], "10.00")]).status_code in (403, 404, 409)
