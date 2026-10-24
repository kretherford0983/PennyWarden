"""2.1.0 (#260): Electronic payment on withdrawals - method, an optional number that is either from the check sequence
(CR-011/CR-012) or a payment reference (never in the sequence), the register badge/filter, the reports and the
Payments module interlock (no check printed for an electronic payment; a printed check can't become electronic)."""
from __future__ import annotations

import pytest

from fmpoc.services import register as reg
from test_v200_checks import do_print, make_signer, setup  # noqa: F401  (fixture)


_n = iter(range(1, 10_000))


def _w(env, base, expect=201, **kw):
    amount = kw.pop("amount", None) or f"{20 + next(_n)}.00"   # distinct amounts: no possible-duplicate warning
    lines = kw.pop("lines", None) or [{"budget_id": base["exp_leaf"], "amount": amount, "description": "Utility"}]
    return env.txn(base["acct"]["id"], "WITHDRAWAL", lines, expect=expect, **kw)


def _missing(env, base):
    return env.bu.get(f"/api/check-review?bank_account_id={base['acct']['id']}").json()["missing"]


def test_electronic_with_method_and_reference(env, base):
    t = _w(env, base, electronic_payment=True, payment_method="ACH", payment_reference="CONF-88213")
    assert t["electronic_payment"] and t["payment_method"] == "ACH" and t["payment_reference"] == "CONF-88213"
    assert t["check_number"] is None and t["payment_method_label"] == "ACH / bill pay"
    other = _w(env, base, electronic_payment=True, payment_method="OTHER", payment_method_other="Zelle")
    assert other["payment_method_label"] == "Zelle"
    # a plain withdrawal is not electronic
    plain = _w(env, base)
    assert plain["electronic_payment"] is False and plain["payment_method"] is None


@pytest.mark.parametrize("kw,field", [
    ({"electronic_payment": True}, "payment_method"),
    ({"electronic_payment": True, "payment_method": "OTHER"}, "payment_method_other"),
    ({"payment_method": "ACH"}, "electronic_payment"),
    ({"payment_reference": "X1"}, "electronic_payment"),
    ({"electronic_payment": True, "payment_method": "WIRE", "check_number": "501", "payment_reference": "W1"},
     "payment_reference"),
    ({"electronic_payment": True, "payment_method": "PAYPAL"}, None),
])
def test_validation(env, base, kw, field):
    r = env.ru.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "WITHDRAWAL",
                                          "allocations": [{"budget_id": base["exp_leaf"], "amount": "5.00"}], **kw})
    assert r.status_code == 422, r.text
    if field:
        assert any(e.get("field") == field for e in r.json()["error"].get("errors", [])), r.text


def test_deposit_refuses_electronic(env, base):
    r = env.ru.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "DEPOSIT",
                                          "electronic_payment": True, "payment_method": "ACH",
                                          "allocations": [{"budget_id": base["inc_leaf"], "amount": "5.00"}]})
    assert r.status_code == 422 and "Withdrawals only" in r.text


def test_sequence_number_counts_reference_does_not(env, base):
    _w(env, base, check_number="100")
    _w(env, base, check_number="103")
    # an electronic payment with a number from our sequence fills the gap like a check
    _w(env, base, electronic_payment=True, payment_method="ACH", check_number="101")
    # a reference never enters the sequence: no gap up to 98765 appears
    _w(env, base, electronic_payment=True, payment_method="ONLINE_PORTAL", payment_reference="98765")
    gaps = [(m["first_number"], m["last_number"]) for m in _missing(env, base)]
    assert gaps == [(102, 102)]
    # the check number stays unique across checks and electronic payments (CR-011)
    r = env.ru.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "WITHDRAWAL",
                                          "check_number": "101",
                                          "allocations": [{"budget_id": base["exp_leaf"], "amount": "5.00"}]})
    assert r.status_code == 409
    # a reference equal to a check number is fine; a repeated reference is not
    _w(env, base, electronic_payment=True, payment_method="WIRE", payment_reference="100")
    r = env.ru.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "WITHDRAWAL",
                                          "electronic_payment": True, "payment_method": "WIRE",
                                          "payment_reference": "conf-x", "allocations": [
                                              {"budget_id": base["exp_leaf"], "amount": "5.00"}]})
    assert r.status_code == 201
    r = env.ru.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "WITHDRAWAL",
                                          "electronic_payment": True, "payment_method": "WIRE",
                                          "payment_reference": "CONF-X", "allocations": [
                                              {"budget_id": base["exp_leaf"], "amount": "5.00"}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_PAYMENT_REFERENCE"


def test_edit_rules_audit_and_turning_off(env, base):
    t = _w(env, base, clear_date="2026-08-03")
    # cleared: the change needs the cleared-edit confirmation, like any financial edit
    r = env.ru.patch(f"/api/transactions/{t['id']}", {"electronic_payment": True, "payment_method": "DEBIT_CARD"})
    assert r.status_code == 409 and "CLEARED_EDIT" in r.text
    r = env.ru.patch(f"/api/transactions/{t['id']}", {"electronic_payment": True, "payment_method": "DEBIT_CARD",
                                                      "confirmations": ["CLEARED_EDIT"]})
    assert r.status_code == 200 and r.json()["electronic_payment"]
    items = env.auditor.get(f"/api/audit-events?object_type=register_transaction&object_id={t['id']}").json()["items"]
    upd = next(e for e in items if e["action"] == "TRANSACTION_UPDATED")
    assert upd["before"]["electronic_payment"] is False and upd["after"]["payment_method"] == "DEBIT_CARD"
    # turning it off clears method and reference
    r = env.ru.patch(f"/api/transactions/{t['id']}", {"electronic_payment": False, "confirmations": ["CLEARED_EDIT"]})
    assert r.status_code == 200 and r.json()["payment_method"] is None
    # changing to a Deposit while electronic is refused
    e = _w(env, base, electronic_payment=True, payment_method="ACH")
    r = env.ru.patch(f"/api/transactions/{e['id']}", {"transaction_type": "DEPOSIT", "allocations": [
        {"budget_id": base["inc_leaf"], "amount": e["withdrawal"]}], "confirmations": ["TYPE_CHANGE"]})
    assert r.status_code == 422 and "Withdrawals only" in r.text


def test_register_filter_badge_data_and_search(env, base):
    chk = _w(env, base, check_number="200")
    ele = _w(env, base, electronic_payment=True, payment_method="ACH", payment_reference="ACH-1234")
    none = _w(env, base)
    dep = env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "5.00"}])

    def ids(q):
        return [t["id"] for t in env.bu.get(f"/api/register?bank_account_id={base['acct']['id']}{q}").json()["transactions"]]
    assert ids("&payment=electronic") == [ele["id"]]
    assert ids("&payment=check") == [chk["id"]]
    assert ids("&payment=none") == [none["id"]]
    assert dep["id"] in ids("")
    assert ids("&search=ach-1234") == [ele["id"]]
    assert env.bu.get(f"/api/register?bank_account_id={base['acct']['id']}&payment=cash").status_code == 422


def test_payment_text_for_reports():
    from types import SimpleNamespace as N
    assert reg.payment_text(N(electronic_payment=True, payment_method="ACH", payment_method_other=None,
                              check_number=None, payment_reference="R9")) == "Electronic (ACH / bill pay), ref. R9"
    assert reg.payment_text(N(electronic_payment=True, payment_method="WIRE", payment_method_other=None,
                              check_number="101", payment_reference=None)) == "Electronic (Wire), check #101"
    assert reg.payment_text(N(electronic_payment=False, payment_method=None, payment_method_other=None,
                              check_number="77", payment_reference=None)) == "77"


def test_audit_report_shows_electronic(env, base):
    _w(env, base, electronic_payment=True, payment_method="ONLINE_PORTAL", payment_reference="PORTAL-55")
    r = env.auditor.get(f"/api/reports/audit?fiscal_year_id={base['fy']['id']}&download=true")
    assert r.status_code == 200, r.text[:300]
    from pypdf import PdfReader
    import io
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "Electronic (Online portal), ref. PORTAL-55" in text


# ------------------------------------------------------------------ Payments module interlock
def test_no_check_for_an_electronic_payment(env, setup):
    tid = setup["txn"]["id"]
    r = env.ru.patch(f"/api/transactions/{tid}", {"electronic_payment": True, "payment_method": "ACH"})
    assert r.status_code == 200, r.text
    r = do_print(env, setup)
    assert r.status_code == 409 and "electronically" in r.text
    assert env.ru.post(f"/api/checks/transactions/{tid}/spoil",
                       {"reason": "x", "new_check_number": "6176"}).status_code == 409
    # the options still load (letters and envelopes stay optional)
    opts = env.ru.get(f"/api/checks/transactions/{tid}/options")
    assert opts.status_code == 200 and opts.json()["transaction"]["electronic_payment"] is True
    assert env.ru.get(f"/api/checks/transactions/{tid}/documents").status_code == 200


def test_a_printed_check_cant_become_electronic_until_spoiled(env, setup):
    signer = make_signer(env)
    tid = setup["txn"]["id"]
    assert do_print(env, setup, signer_id=signer["id"]).status_code == 200
    r = env.ru.patch(f"/api/transactions/{tid}", {"electronic_payment": True, "payment_method": "ACH"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CHECK_PRINTED"
    r = env.ru.post(f"/api/checks/transactions/{tid}/spoil", {"reason": "never sent", "new_check_number": "6176"})
    assert r.status_code == 200, r.text
    r = env.ru.patch(f"/api/transactions/{tid}", {"electronic_payment": True, "payment_method": "ACH",
                                                  "check_number": None})
    assert r.status_code == 200, r.text


def test_register_says_whether_letter_or_envelope_templates_exist(env, base, setup):
    """2.1.1 (product owner, 2026-10-23): an electronic payment's "Letter or envelope..." showed an empty dialog in a
    workspace without cover letter or envelope templates - the register now reports whether any active one exists,
    and the Register disables the button when none does."""
    _w(env, base, electronic_payment=True, payment_method="ACH")
    url = f"/api/register?bank_account_id={base['acct']['id']}"

    def has():
        return env.bu.get(url).json()["payment_documents"]
    assert has() is False
    env_doc = env.admin.post("/api/checks/documents", {"kind": "ENVELOPE", "name": "Plain #10"})
    assert env_doc.status_code == 201, env_doc.text
    assert has() is True
    r = env.admin.post(f"/api/checks/documents/{env_doc.json()['id']}/flags", {"active": False})
    assert r.status_code == 200, r.text
    assert has() is False                                   # a deactivated template doesn't count
    letter = env.admin.post("/api/checks/documents", {"kind": "LETTER", "name": "Invoices paid"})
    assert letter.status_code == 201, letter.text
    assert has() is True
