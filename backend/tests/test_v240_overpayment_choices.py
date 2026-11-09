"""2.4.0 (#544): what happens to the part of a payment above the invoices - the same choices everywhere: kept on a
budget (a donation, a fundraiser...), applied to the customer's other open invoices, the customer's credit (never
while they still owe) or refunded (the app opens the Refund form; the system writes no withdrawal itself).
Decisions: Kyle, 2026-11-07. BR-INV-OVER-001..003 / AC-INV-OVER-001..004."""
from __future__ import annotations

from test_v240_apply_to_invoice import _dep, grants  # noqa: F401  (fixture)
from test_v240_invoice_payments import ib  # noqa: F401  (fixture)
from test_v240_multi_invoice_payment import URL, _invoice, _post


def test_ac_inv_over_001_no_credit_while_the_customer_owes(env, ib):
    b = _invoice(ib, ib["cust"], "1", "2026-09-01")            # 110.00 still owed besides the 220.00 invoice
    r = _post(env, ib, [(ib["inv"], "220.00")], overpayment="30.00", overpayment_invoice_id=ib["inv"],
              overpayment_kind="CREDIT", confirm_overpayment=True)
    assert r.status_code == 422 and r.json()["error"]["code"] == "CREDIT_WHILE_OWED"
    assert "110.00" in r.json()["error"]["message"]
    # applied to the other open invoice as well, and nothing is owed: the rest can be their credit
    r = _post(env, ib, [(ib["inv"], "220.00"), (b, "110.00")], overpayment="30.00", overpayment_invoice_id=ib["inv"],
              overpayment_kind="CREDIT", confirm_overpayment=True)
    assert r.status_code == 201, r.text
    assert env.ru.get("/api/invoices/credit", params={"customer_entity_id": ib["cust"]}).json()["total"] == "30.00"


def test_ac_inv_over_002_the_rest_on_a_budget(env, base, ib, grants):
    opts = env.ru.get(f"{URL}/extra-budgets", params={"date": "2026-09-25"}).json()
    assert grants in [o["id"] for o in opts] and not [o for o in opts if o["invoiced_income"]]
    r = _post(env, ib, [(ib["inv"], "220.00")], overpayment="30.00", overpayment_kind="BUDGET",
              overpayment_budget_id=base["inc_leaf"], confirm_overpayment=True)
    assert r.status_code == 422 and r.json()["error"]["errors"][0]["field"] == "overpayment_budget_id"
    r = _post(env, ib, [(ib["inv"], "220.00")], overpayment="30.00", overpayment_kind="BUDGET",
              overpayment_budget_id=grants)
    assert r.status_code == 409 and "Grants" in r.json()["error"]["message"]
    r = _post(env, ib, [(ib["inv"], "220.00")], overpayment="30.00", overpayment_kind="BUDGET",
              overpayment_budget_id=grants, confirm_overpayment=True)
    assert r.status_code == 201, r.text
    t, i = r.json()["transaction"], r.json()["invoices"][0]
    assert t["total"] == "250.00" and [a["amount"] for a in t["allocations"] if a["budget_id"] == grants] == ["30.00"]
    assert i["status"] == "PAID" and i["payments"]["overpaid"] == "0.00" and i["payments"]["paid"] == "220.00"


def test_ac_inv_over_003_refund_is_left_to_the_refund_form(env, ib):
    _invoice(ib, ib["cust"], "1", "2026-09-01")                # still owed: a refund is allowed, credit is not
    r = _post(env, ib, [(ib["inv"], "220.00")], overpayment="30.00", overpayment_invoice_id=ib["inv"],
              overpayment_kind="REFUND")
    assert r.status_code == 409 and "refunded next" in r.json()["error"]["message"]
    r = _post(env, ib, [(ib["inv"], "220.00")], overpayment="30.00", overpayment_invoice_id=ib["inv"],
              overpayment_kind="REFUND", confirm_overpayment=True)
    assert r.status_code == 201, r.text
    assert r.json()["invoices"][0]["payments"]["refundable"] == "30.00"
    r = env.ru.post(f"/api/invoices/{ib['inv']}/refunds", {"bank_account_id": ib["acct"], "amount": "30.00",
                                                           "transaction_date": "2026-09-26", "check_number": "1050"})
    assert r.status_code == 201, r.text
    assert r.json()["transaction"]["check_number"] == "1050" and r.json()["invoice"]["payments"]["refundable"] == "0.00"


def test_ac_inv_over_004_register_apply_counts_every_line(env, ib, grants):
    b = _invoice(ib, ib["cust"], "1", "2026-09-01")
    line = {"budget_id": grants, "amount": "250.00", "apply_extra": "CREDIT", "apply_extra_invoice_id": ib["inv"],
            "apply_to": [{"invoice_id": ib["inv"], "amount": "220.00"}]}
    r = _dep(env, ib, [line], expect=422, confirmations=["OVERPAYMENT"])
    assert r["error"]["code"] == "CREDIT_WHILE_OWED" and r["error"]["errors"][0]["field"] == "allocations.0.apply_extra"
    # another line of the same deposit pays the other invoice: nothing is owed, the extra can be credit
    other = {"budget_id": grants, "amount": "110.00", "apply_to": [{"invoice_id": b, "amount": "110.00"}]}
    t = _dep(env, ib, [line, other], confirmations=["OVERPAYMENT"])
    assert t["total"] == "360.00"
    # Link a deposit moving an ordinary line: the same rule
    c = _invoice(ib, ib["cust"], "2", "2026-09-10")            # 220.00
    d = _invoice(ib, ib["cust"], "1", "2026-09-11")            # 110.00, still owed
    dep = _dep(env, ib, [{"budget_id": grants, "amount": "250.00"}])
    r = env.ru.post(f"/api/invoices/{c}/links", {"allocation_id": dep["allocations"][0]["id"], "extra": "CREDIT",
                                                 "confirmations": ["OVERPAYMENT"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CREDIT_WHILE_OWED", r.text
    assert d
