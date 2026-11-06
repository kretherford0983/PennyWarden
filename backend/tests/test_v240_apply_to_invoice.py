"""2.4.0 (#533): a deposit entered in the Register first reaches its invoice - "Apply to invoice" on an allocation
(the applied part becomes the invoice's splits, linked, when saved), and Link a deposit... moves a line on an ordinary
Income budget onto the invoice's budgets. Decisions: Kyle, 2026-11-06. BR-INV-PAY-010..012 / AC-INV-PAY-012..015."""
from __future__ import annotations

import pytest

from test_v240_invoice_payments import ib  # noqa: F401  (fixture)


@pytest.fixture
def grants(env, base, ib):
    env.budget(base["fy"]["id"], "4100", "Grants", "INCOME", "5000.00")
    sel = {o["label"]: o["id"] for o in env.selectable(base["fy"]["id"], "DEPOSIT")}
    return sel["4100 Grants"]


def _dep(env, ib, allocs, expect=201, **kw):
    return env.txn(ib["acct"], "DEPOSIT", allocs, date="2026-09-25", expect=expect, entity_id=ib["cust"], **kw)


def _inv(env, ib):
    return env.ru.get(f"/api/invoices/{ib['inv']}").json()


def test_ac_inv_pay_012_apply_part_of_a_deposit_in_the_register(env, base, ib, grants):
    # the invoice's budget picked by hand is still refused...
    r = env.ru.post("/api/transactions", {"bank_account_id": ib["acct"], "transaction_type": "DEPOSIT",
                                           "transaction_date": "2026-09-25", "entity_id": ib["cust"],
                                           "allocations": [{"budget_id": base["inc_leaf"], "amount": "220.00"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVOICE_PAYMENT_REQUIRED"
    # ...but applied to the invoice it becomes the invoice's splits; the fundraiser line stays as entered
    t = _dep(env, ib, [{"budget_id": base["inc_leaf"], "amount": "220.00",
                        "apply_to": [{"invoice_id": ib["inv"], "amount": "220.00"}]},
                       {"budget_id": grants, "amount": "150.00", "description": "Golf outing"}])
    assert t["total"] == "370.00"
    paying = [a for a in t["allocations"] if a["invoice"]]
    assert {a["invoice"]["id"] for a in paying} == {ib["inv"]} and sum(float(a["amount"]) for a in paying) == 220
    assert [a["description"] for a in t["allocations"] if not a["invoice"]] == ["Golf outing"]
    i = _inv(env, ib)
    assert i["status"] == "PAID" and i["payments"]["paid"] == "220.00"


def test_ac_inv_pay_013_the_extra_above_the_invoices(env, base, ib, grants):
    line = lambda extra, budget=grants, **kw: [{"budget_id": budget, "amount": "300.00", "apply_extra": extra,  # noqa: E731
                                                "apply_to": [{"invoice_id": ib["inv"], "amount": "220.00"}], **kw}]
    # more than the open balance on the invoice itself
    r = _dep(env, ib, [{"budget_id": grants, "amount": "300.00", "apply_to": [{"invoice_id": ib["inv"], "amount": "300.00"}]}],
             expect=422)
    assert r["error"]["code"] == "OVER_OPEN_BALANCE"
    # the extra on a budget: not an Invoiced Income one
    r = _dep(env, ib, line("BUDGET", base["inc_leaf"]), expect=422)
    assert r["error"]["errors"][0]["field"] == "allocations.0.budget_id"
    # kept as credit: an overpayment on the invoice, confirmed
    r = _dep(env, ib, line("CREDIT"), expect=409)
    assert [w["code"] for w in r["error"]["warnings"]] == ["OVERPAYMENT"]
    t = _dep(env, ib, line("CREDIT"), confirmations=["OVERPAYMENT"])
    assert t["total"] == "300.00" and all(a["invoice"] for a in t["allocations"])
    i = _inv(env, ib)
    assert i["status"] == "PAID" and i["payments"]["overpaid"] == "80.00" and i["payments"]["refundable"] == "80.00"
    # refunded at once: a refund withdrawal of the extra, from the same account
    env.ru.post(f"/api/transactions/{t['id']}/void", {"reason": "Test", "confirm_irreversible": True})
    t = _dep(env, ib, line("REFUND"), confirmations=["OVERPAYMENT", "POSSIBLE_DUPLICATE"])
    i = _inv(env, ib)
    assert i["payments"]["refundable"] == "0.00"
    lst = env.ru.get("/api/register", params={"bank_account_id": ib["acct"]}).json()["transactions"]
    refunds = [x for x in (lst["items"] if isinstance(lst, dict) else lst)
               if x["transaction_type"] == "WITHDRAWAL" and x["status"] == "ACTIVE"]
    assert [x["total"] for x in refunds] == ["80.00"]


def test_ac_inv_pay_013_extra_stays_on_its_budget(env, base, ib, grants):
    t = _dep(env, ib, [{"budget_id": grants, "amount": "300.00", "description": "Check 1042",
                        "apply_to": [{"invoice_id": ib["inv"], "amount": "220.00"}], "apply_extra": "BUDGET"}])
    rest = [a for a in t["allocations"] if not a["invoice"]]
    assert [(a["amount"], a["description"]) for a in rest] == [("80.00", "Check 1042")]
    assert _inv(env, ib)["status"] == "PAID"


def test_ac_inv_pay_014_link_moves_a_line_onto_the_invoice(env, base, ib, grants):
    t = _dep(env, ib, [{"budget_id": grants, "amount": "300.00"}])
    cand = env.ru.get(f"/api/invoices/{ib['inv']}/link-candidates").json()
    c = next(x for x in cand if x["allocation_id"] == t["allocations"][0]["id"])
    assert c["moves"] and c["customer"]
    r = env.ru.post(f"/api/invoices/{ib['inv']}/links", {"allocation_id": c["allocation_id"]})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "PAID"
    after = env.ru.get(f"/api/transactions/{t['id']}").json()
    assert after["total"] == "300.00"
    assert [(a["amount"], a["budget"]["label"].split(" ")[0]) for a in after["allocations"] if not a["invoice"]] == \
        [("80.00", "4100")]                                                    # the rest stays where it was
    # an Invoice Manager can't move register lines
    t2 = _dep(env, ib, [{"budget_id": grants, "amount": "10.00"}], confirmations=["POSSIBLE_DUPLICATE"])
    assert ib["im"].post(f"/api/invoices/{ib['inv']}/links",
                         {"allocation_id": t2["allocations"][0]["id"]}).status_code == 403


def test_ac_inv_pay_015_apply_when_editing_and_another_payer(env, base, ib, grants):
    other = env.entity("Other Payer")["id"]
    t = env.txn(ib["acct"], "DEPOSIT", [{"budget_id": grants, "amount": "100.00"}], date="2026-09-25", entity_id=other)
    a = t["allocations"][0]
    body = {"allocations": [{"id": a["id"], "budget_id": grants, "amount": "100.00",
                             "apply_to": [{"invoice_id": ib["inv"], "amount": "100.00"}]}]}
    r = env.ru.patch(f"/api/transactions/{t['id']}", body)
    assert r.status_code == 409 and "THIRD_PARTY_PAYER" in [w["code"] for w in r.json()["error"]["warnings"]]
    r = env.ru.patch(f"/api/transactions/{t['id']}", {**body, "confirmations": ["THIRD_PARTY_PAYER", "CLEARED_EDIT"]})
    assert r.status_code == 200, r.text
    assert all(x["invoice"] for x in r.json()["allocations"])
    assert _inv(env, ib)["status"] == "PARTLY_PAID"
    # the module off: nothing can be applied
    assert env.admin.put("/api/system/modules", {"invoices": False}).status_code == 200
    r = env.ru.post("/api/transactions", {"bank_account_id": ib["acct"], "transaction_type": "DEPOSIT",
                                           "transaction_date": "2026-09-25", "allocations": [
                                               {"budget_id": grants, "amount": "5.00",
                                                "apply_to": [{"invoice_id": ib["inv"], "amount": "5.00"}]}]})
    assert r.status_code in (403, 404, 409)
