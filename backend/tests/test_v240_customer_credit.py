"""2.4.0 (#534): customer account credit - an overpayment not refunded is the customer's credit; it is applied when
their next invoice is sent (oldest first), shown on the invoice and its PDF, can be taken back off, refunded, or moved
to another budget. Decisions: Kyle, 2026-11-06. BR-INV-CR-001..004 / AC-INV-CR-001..005."""
from __future__ import annotations

import io

from pypdf import PdfReader

from test_v240_invoice_payments import ib  # noqa: F401  (fixture)


def _overpay(env, ib, amount="250.00", date="2026-09-20"):
    """$220 invoice paid $250: $30 credit."""
    r = env.ru.post(f"/api/invoices/{ib['inv']}/payments", {"bank_account_id": ib["acct"], "amount": amount,
                                                            "transaction_date": date, "confirm_overpayment": True})
    assert r.status_code == 201, r.text
    return r.json()


def _new_invoice(env, ib, qty="1"):
    i = ib["im"].post("/api/invoices", {"customer_entity_id": ib["cust"], "invoice_date": "2026-10-01",
                                        "lines": [{"product_id": ib["dues"], "quantity": qty}]})
    assert i.status_code == 201, i.text
    return i.json()




def test_ac_inv_cr_001_credit_is_applied_when_the_next_invoice_is_sent(env, base, ib):
    _overpay(env, ib)
    c = env.ru.get("/api/invoices/credit", params={"customer_entity_id": ib["cust"]}).json()
    assert c["total"] == "30.00" and c["usable"] == "30.00"
    i = _new_invoice(env, ib)                                   # $110
    sent = ib["im"].post(f"/api/invoices/{i['id']}/send")
    assert sent.status_code == 200, sent.text
    p = sent.json()["payments"]
    assert p["credit_applied"] == "30.00" and p["paid"] == "30.00" and p["open"] == "80.00"
    assert sent.json()["status"] == "PARTLY_PAID"
    assert [x["credit_from"]["id"] for x in p["links"] if not x["unlinked"]] == [ib["inv"]] * len(
        [x for x in p["links"] if not x["unlinked"]])
    first = env.ru.get(f"/api/invoices/{ib['inv']}").json()
    assert first["status"] == "PAID" and first["payments"]["refundable"] == "0.00"   # the credit is used
    assert env.ru.get("/api/invoices/credit", params={"customer_entity_id": ib["cust"]}).json()["total"] == "0.00"
    # the deposit didn't change: same total, the money moved from the overpayment to the new invoice's lines
    t = env.ru.get(f"/api/transactions/{p['links'][0]['transaction_id']}").json()
    assert t["total"] == "250.00"
    ev = env.auditor.get(f"/api/audit-events?action=INVOICE_CREDIT_APPLIED&object_id={i['id']}").json()["items"]
    assert ev and ev[0]["after"]["amount"] == "30.00"


def test_ac_inv_cr_002_pdf_shows_new_charges_credit_and_total_due(env, base, ib):
    _overpay(env, ib)
    i = _new_invoice(env, ib)
    ib["im"].post(f"/api/invoices/{i['id']}/send")
    pdf = ib["im"].get(f"/api/invoices/{i['id']}/pdf")
    assert pdf.status_code == 200
    text = " ".join(pg.extract_text() for pg in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "New charges" in text and "Account credit applied" in text and "-$30.00" in text and "Total due" in text
    assert "$80.00" in text


def test_ac_inv_cr_003_credit_larger_than_the_invoice_and_taken_back_off(env, base, ib):
    _overpay(env, ib, "400.00")                                 # $180 credit
    i = _new_invoice(env, ib)                                   # $110
    s = ib["im"].post(f"/api/invoices/{i['id']}/send").json()
    assert s["status"] == "PAID" and s["payments"]["credit_applied"] == "110.00"
    assert env.ru.get("/api/invoices/credit", params={"customer_entity_id": ib["cust"]}).json()["total"] == "70.00"
    # an Invoice Manager can't take it back off; a Register User can, with a reason
    assert ib["im"].post(f"/api/invoices/{i['id']}/credit/remove", {"reason": "x"}).status_code == 403
    r = env.ru.post(f"/api/invoices/{i['id']}/credit/remove", {"reason": "Customer asked for a refund instead"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SENT" and r.json()["payments"]["credit_applied"] == "0.00"
    assert env.ru.get("/api/invoices/credit", params={"customer_entity_id": ib["cust"]}).json()["total"] == "180.00"


def test_ac_inv_cr_004_refund_and_move_credit(env, base, ib):
    _overpay(env, ib, "300.00")                                 # $80 credit
    r = env.ru.post(f"/api/invoices/{ib['inv']}/refunds", {"bank_account_id": ib["acct"], "amount": "20.00",
                                                           "transaction_date": "2026-09-25"})
    assert r.status_code == 201, r.text
    assert env.ru.get("/api/invoices/credit", params={"customer_entity_id": ib["cust"]}).json()["total"] == "60.00"
    # moving the overpayment line (80) when 20 of it was refunded: refused - only what is left can move
    links = env.ru.get(f"/api/invoices/{ib['inv']}").json()["payments"]["links"]
    over = next(x for x in links if x["kind"] == "OVERPAYMENT" and not x["unlinked"])
    grants = env.budget(base["fy"]["id"], "4100", "Grants", "INCOME", "500.00")
    sel = {o["label"]: o["id"] for o in env.selectable(base["fy"]["id"], "DEPOSIT")}
    r = env.ru.post(f"/api/invoices/{ib['inv']}/links/{over['id']}/unlink",
                    {"move_to_budget_id": sel["4100 Grants"], "reason": "Keep as a donation"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PARTLY_REFUNDED"
    assert grants["id"]


def test_ac_inv_cr_005_existing_overpayments_count_and_none_without_credit(env, base, ib):
    i = _new_invoice(env, ib)
    s = ib["im"].post(f"/api/invoices/{i['id']}/send").json()
    assert s["status"] == "SENT" and s["payments"]["credit_applied"] == "0.00"
    assert s["payments"]["customer_credit"]["total"] == "0.00"
    _overpay(env, ib)
    j = env.ru.get(f"/api/invoices/{i['id']}").json()
    assert j["payments"]["customer_credit"]["total"] == "30.00"            # shown on the customer's other invoice


def test_statement_shows_the_account_credit(env, base, ib):
    _overpay(env, ib)
    r = env.ru.get("/api/invoices/reports/inv-statement", params={"customer_entity_id": ib["cust"],
                                                                  "date_from": "2026-09-01", "date_to": "2026-09-30"})
    assert r.status_code == 200, r.text
    sec = r.json()["sections"][-1]
    assert sec["heading"].startswith("Account credit") and sec["totals"]["amount"] == "30.00"
